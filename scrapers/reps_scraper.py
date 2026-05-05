# -*- coding: utf-8 -*-
"""
Scraper genérico para todas las consultas REPS (MinSalud).

Realiza un único login y descarga cada endpoint en secuencia:
  - Prestadores habilitados
  - Sedes
  - Servicios por sede
  - Capacidades instaladas
  - Medidas de seguridad
  - Sanciones

Salidas: data/raw/reps_<nombre>_YYYY_MM.csv (pipe-delimited)
"""

import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

URL_LOGIN = 'https://prestadores.minsalud.gov.co/habilitacion/'

ENDPOINTS = [
    {
        'name': 'prestadores',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/habilitados_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'Prestadores.csv',
    },
    {
        'name': 'sedes',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/sedes_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'Sedes.csv',
    },
    {
        'name': 'servicios',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/serviciossedes_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'ServiciosSedes.csv',
    },
    {
        'name': 'capacidad',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/capacidadesinstaladas_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'CapacidadesInstaladas.csv',
    },
    {
        'name': 'medidas_seguridad',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/medidasseguridad_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'MedidasSeguridad.csv',
    },
    {
        'name': 'sanciones',
        'url': 'https://prestadores.minsalud.gov.co/habilitacion/consultas/sanciones_reps.aspx',
        'btn_buscar': '_ctl0_ibBuscarFtr',
        'btn_export': '_ctl0_ContentPlaceHolder1_ibText',
        'input_sep': '_ctl0_ContentPlaceHolder1_tbSeparator',
        'filename': 'Sanciones.csv',
    },
]


def _limpia(s: str) -> str:
    if s is None:
        return ''
    s = str(s).replace('﻿', '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def _esperar_descarga(desc_dir: str, filename: str, timeout: int = 180,
                      existing_before: set | None = None) -> str | None:
    """Wait for a download to complete. If the server uses the wrong filename,
    detect any new completed file and rename it to the expected filename."""
    t0 = time.time()
    target = os.path.join(desc_dir, filename)
    before = existing_before or set()
    while time.time() - t0 < timeout:
        files = os.listdir(desc_dir)
        # Check expected filename first
        if filename.lower() in [f.lower() for f in files]:
            return target
        # Detect any new completed (non-temp) file not present before export click
        new_done = [f for f in files
                    if f not in before
                    and not f.endswith(('.crdownload', '.tmp'))]
        if new_done:
            actual = os.path.join(desc_dir, new_done[0])
            os.rename(actual, target)
            return target
        time.sleep(1)
    # Rename any leftover crdownload
    crs = [f for f in os.listdir(desc_dir) if f.endswith('.crdownload')]
    if crs:
        tmp = os.path.join(desc_dir, crs[0])
        try:
            os.rename(tmp, target)
            return target
        except Exception:
            pass
    return None


def _leer_csv_tolerante(path: str) -> pl.DataFrame:
    """Read CSV with latin1 encoding, auto-detecting | or ; separator, repairing malformed rows."""
    rows = []
    cols = []
    with open(path, 'r', encoding='latin1', errors='replace') as f:
        header = f.readline().rstrip('\n\r').replace('﻿', '')
        sep = '|' if len(header.split('|')) >= len(header.split(';')) else ';'
        cols = [_limpia(c) for c in header.split(sep)]
        N = len(cols)
        for line in f:
            parts = line.rstrip('\n\r').split(sep)
            if len(parts) == N:
                rows.append(parts)
            elif len(parts) > N:
                rows.append(parts[:N - 1] + [sep.join(parts[N - 1:])])
            else:
                rows.append(parts + [''] * (N - len(parts)))
    if not rows:
        return pl.DataFrame({c: [] for c in cols})
    # Build polars DataFrame from lists
    data = {col: [r[i] if i < len(r) else '' for r in rows] for i, col in enumerate(cols)}
    return pl.DataFrame(data)


def _make_driver(download_dir: str) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument('--window-position=-32000,-32000')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--incognito')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'safebrowsing.enabled': True,
    })
    driver = webdriver.Chrome(options=opts)
    try:
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': download_dir,
        })
    except Exception:
        pass
    return driver


def _login(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, 30)
    log.info('REPS: abriendo login...')
    driver.get(URL_LOGIN)
    time.sleep(2)
    driver.switch_to.frame('areawork')
    driver.execute_script("""
        try {
            let m = document.querySelector('#exampleModal');
            if(m){ m.style.display='none'; m.classList.remove('show'); }
            let b = document.querySelector('.modal-backdrop');
            if(b) b.remove();
            document.body.classList.remove('modal-open');
        } catch(e){}
    """)
    time.sleep(1)
    wait.until(EC.element_to_be_clickable((By.ID, 'Button1'))).click()
    time.sleep(3)
    driver.switch_to.default_content()
    log.info('REPS: login OK')


def _scrape_endpoint(driver: webdriver.Chrome, ep: dict, download_dir: str, stamp: str) -> pl.DataFrame | None:
    """Navigate to one REPS endpoint, export CSV, parse and return DataFrame."""
    wait = WebDriverWait(driver, 30)
    name = ep['name']

    # Clean any previous CSV with this filename
    target_path = os.path.join(download_dir, ep['filename'])
    if os.path.exists(target_path):
        os.remove(target_path)

    log.info(f'REPS [{name}]: navegando a {ep["url"]}')
    driver.get(ep['url'])
    time.sleep(2)

    try:
        btn_buscar = wait.until(EC.element_to_be_clickable((By.ID, ep['btn_buscar'])))
        btn_buscar.click()
        time.sleep(5)
    except TimeoutException:
        log.warning(f'REPS [{name}]: no se encontró botón de búsqueda.')
        return None

    try:
        sep_field = wait.until(EC.presence_of_element_located((By.ID, ep['input_sep'])))
        driver.execute_script("arguments[0].value='|';", sep_field)
        time.sleep(1)
    except TimeoutException:
        log.warning(f'REPS [{name}]: no se encontró campo de separador.')

    try:
        btn_exp = wait.until(EC.element_to_be_clickable((By.ID, ep['btn_export'])))
        files_before = set(os.listdir(download_dir))
        btn_exp.click()
    except TimeoutException:
        log.warning(f'REPS [{name}]: no se encontró botón de exportar.')
        return None

    path = _esperar_descarga(download_dir, ep['filename'], timeout=300,
                             existing_before=files_before)
    if not path or not os.path.exists(path):
        log.warning(f'REPS [{name}]: descarga no completada.')
        return None

    log.info(f'REPS [{name}]: descargado → {path}')
    try:
        df = _leer_csv_tolerante(path)
        log.info(f'REPS [{name}]: {len(df):,} filas, {len(df.columns)} columnas')
        return df
    except Exception as e:
        log.warning(f'REPS [{name}]: error leyendo CSV — {e}')
        return None


def _register_duckdb(parquet_dir: Path, db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    for ep in ENDPOINTS:
        name = ep['name']
        files = sorted(parquet_dir.glob(f'reps_{name}_*.parquet'))
        if not files:
            continue
        glob = f'{parquet_dir.as_posix()}/reps_{name}_*.parquet'
        table = f'reps_{name}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{glob}')")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'  DuckDB [{table}]: {n:,} filas')
    con.close()


def run(base_dir: str = None, endpoints: list[str] | None = None) -> None:
    """
    Scrape REPS endpoints.

    Args:
        base_dir: project root directory
        endpoints: list of endpoint names to scrape (None = all)
    """
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    db_path = base_dir / 'data' / 'informe_regional.duckdb'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    import tempfile
    download_dir = tempfile.mkdtemp()

    stamp = datetime.now().strftime('%Y_%m')
    eps = [ep for ep in ENDPOINTS if endpoints is None or ep['name'] in endpoints]

    # Skip endpoints whose parquet already exists for this month
    eps_to_run = []
    for ep in eps:
        out = parquet_dir / f"reps_{ep['name']}_{stamp}.parquet"
        if out.exists():
            log.info(f'REPS [{ep["name"]}]: ya existe {out}, omitiendo.')
        else:
            eps_to_run.append(ep)

    if not eps_to_run:
        print('reps_scraper: todos los archivos ya existen. Omitiendo.')
        _register_duckdb(parquet_dir, db_path)
        return

    driver = _make_driver(download_dir)
    try:
        _login(driver)

        for ep in eps_to_run:
            df = _scrape_endpoint(driver, ep, download_dir, stamp)
            if df is not None and len(df) > 0:
                out = parquet_dir / f"reps_{ep['name']}_{stamp}.parquet"
                df.write_parquet(out, compression='zstd')
                print(f'  -> {out} ({len(df):,} filas)')
            else:
                print(f'  -> REPS [{ep["name"]}]: sin datos o error')
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        import shutil
        try:
            shutil.rmtree(download_dir, ignore_errors=True)
        except Exception:
            pass

    _register_duckdb(parquet_dir, db_path)
    print('reps_scraper OK')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
