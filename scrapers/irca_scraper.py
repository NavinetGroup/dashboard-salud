# -*- coding: utf-8 -*-
"""
Scraper IRCA (Índice de Riesgo para la Calidad del Agua Potable) desde SIVICAP (INS).

Flujo:
1. Selenium headless login con usuario invitado.
2. Navegar al reporte municipal mensual y descargar CSV.
3. Normalizar y guardar directamente en data/parquet/irca_YYYY_MM.parquet.
4. Registrar tabla en data/informe_regional.duckdb.
"""

import logging
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl
import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select

log = logging.getLogger(__name__)

SIVICAP_LOGIN = 'https://sivicap.ins.gov.co/SIVICAP/Account/Login'
SIVICAP_REPORT = 'https://sivicap.ins.gov.co/SIVICAP/ReportesCG/ReportesSIVICAP?menuId=228'
SIVICAP_USER = 'invitado@ins.gov.co'
SIVICAP_PASS = '123456'
CHROME_VERSION = 147

COLUMN_MAP = {
    'Anio': 'anio',
    'Mes': 'mes',
    'Codigo Dep': 'codigo_dep',
    'Nombre Dep': 'nombre_dep',
    'Codigo Mun': 'codigo_mun',
    'Municipio': 'municipio',
    'Cantidad Muestras': 'n_muestras',
    'Promedio Parametros': 'promedio_parametros',
    'Promedio': 'promedio_irca',
    'Nivel de Riesgo': 'nivel_riesgo',
    'Cantidad Muestras Urbanas': 'n_muestras_urbano',
    'Promedio Parametros Urbano': 'promedio_parametros_urbano',
    'Promedio IRCA Urbano': 'promedio_irca_urbano',
    'Nivel Riesgo Urbano': 'nivel_riesgo_urbano',
    'Cantidad Muestras Rural': 'n_muestras_rural',
    'Promedio Parametros Rural': 'promedio_parametros_rural',
    'Promedio IRCA Rural': 'promedio_irca_rural',
    'Nivel Riesgo Rural': 'nivel_riesgo_rural',
}


def _normalize(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.replace('﻿', '').replace('\xa0', ' ')
    s = unicodedata.normalize('NFKC', s)
    return ' '.join(s.split()).strip()


def _make_driver(download_dir: str) -> uc.Chrome:
    opts = uc.ChromeOptions()
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'safebrowsing.enabled': True,
    })
    driver = uc.Chrome(options=opts, version_main=CHROME_VERSION)
    try:
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': download_dir,
        })
    except Exception:
        pass
    return driver


def _wait_download(download_dir: str, prefix: str, timeout: int = 120) -> Path | None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        files = list(Path(download_dir).glob(f'{prefix}*'))
        done = [f for f in files if f.suffix.lower() not in ('.crdownload', '.tmp')]
        if done:
            return max(done, key=lambda f: f.stat().st_mtime)
        time.sleep(2)
    return None


def _login(driver: uc.Chrome, wait: WebDriverWait) -> bool:
    """Log in to SIVICAP using undetected-chromedriver to bypass reCAPTCHA. Returns True on success."""
    log.info('SIVICAP: abriendo login...')
    driver.get(SIVICAP_LOGIN)
    time.sleep(4)

    try:
        driver.find_element(By.ID, 'Email').send_keys(SIVICAP_USER)
        driver.find_element(By.ID, 'Password').send_keys(SIVICAP_PASS)
        time.sleep(1)
    except Exception as e:
        log.warning(f'SIVICAP: no se encontraron campos de login — {e}')
        return False

    try:
        captcha_frame = driver.find_element(By.CSS_SELECTOR, 'iframe[title*="reCAPTCHA"]')
        driver.switch_to.frame(captcha_frame)
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, '.recaptcha-checkbox').click()
        driver.switch_to.default_content()
        # Wait for reCAPTCHA response token to be populated (up to 30s)
        for _ in range(30):
            token = driver.execute_script("return document.getElementById('g-recaptcha-response').value;")
            if token:
                log.info('SIVICAP: reCAPTCHA resuelto.')
                break
            time.sleep(1)
        else:
            log.warning('SIVICAP: reCAPTCHA no se resolvió en 30s.')
            return False
    except Exception as e:
        log.warning(f'SIVICAP: no se pudo resolver reCAPTCHA — {e}')
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False

    try:
        submit = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type=submit]')))
        driver.execute_script("arguments[0].click();", submit)
        time.sleep(5)
    except TimeoutException:
        log.warning('SIVICAP: botón de submit no apareció tras reCAPTCHA.')
        return False

    if 'login' in driver.current_url.lower():
        log.warning('SIVICAP: login fallido — sigue en la página de login.')
        return False

    log.info(f'SIVICAP: login OK ({driver.current_url})')
    return True


def _scrape_sivicap(download_dir: str) -> Path | None:
    """Download IRCA monthly-per-municipality CSV from SIVICAP. Returns local path or None."""
    driver = _make_driver(download_dir)
    try:
        wait = WebDriverWait(driver, 30)

        if not _login(driver, wait):
            return None

        log.info('SIVICAP: navegando al reporte IRCA municipal...')
        driver.get(SIVICAP_REPORT)
        time.sleep(5)

        # Select report type: IRCA mensual por municipio
        try:
            report_select = wait.until(EC.presence_of_element_located((By.TAG_NAME, 'select')))
            sel = Select(report_select)
            # Prefer Resolución 622/2020; fall back to Decreto 1575/2007
            target_texts = [
                'mensual por municipio (Resolución 622/2020)',
                'mensual por municipio (Decreto 1575/2007)',
                'mensual por municipio',
            ]
            chosen = None
            for txt in target_texts:
                for opt in sel.options:
                    if txt.lower() in opt.text.lower():
                        chosen = opt.get_attribute('value')
                        log.info(f'SIVICAP: seleccionando reporte "{opt.text}"')
                        break
                if chosen:
                    break
            if chosen is None:
                log.warning('SIVICAP: no se encontró reporte IRCA mensual por municipio.')
                return None
            sel.select_by_value(chosen)
            time.sleep(3)
        except TimeoutException:
            log.warning('SIVICAP: no se encontró selector de reportes.')
            return None

        # Apply filters and generate report
        try:
            gen_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'generar') or contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'consultar') or contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'buscar')]")
            ))
            gen_btn.click()
            log.info('SIVICAP: generando reporte...')
            time.sleep(5)
        except TimeoutException:
            log.warning('SIVICAP: no se encontró botón generar/consultar.')

        # Find export/download button
        try:
            export_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'exportar') or contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'descargar') or contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'csv') or contains(@id,'export') or contains(@class,'export') or contains(@id,'download')]")
            ))
            export_btn.click()
            log.info('SIVICAP: descargando CSV...')
            time.sleep(3)
        except TimeoutException:
            try:
                csv_link = driver.find_element(By.XPATH, "//a[contains(@href,'.csv') or contains(translate(normalize-space(text()),'CSV','csv'),'csv')]")
                csv_link.click()
                log.info('SIVICAP: descargando via link CSV...')
                time.sleep(3)
            except Exception:
                log.warning('SIVICAP: no se encontró botón de exportar.')
                driver.save_screenshot(str(Path(download_dir) / 'sivicap_debug.png'))
                return None

        downloaded = _wait_download(download_dir, 'RptIrca', timeout=90)
        if not downloaded:
            downloaded = _wait_download(download_dir, '', timeout=30)
        return downloaded

    except WebDriverException as e:
        log.warning(f'SIVICAP: error de Selenium — {e}')
        return None
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _parse_irca(path: Path) -> pl.DataFrame | None:
    """Parse IRCA CSV (semicolon-delimited, latin1) into a tidy Polars DataFrame."""
    df = None
    for sep, enc in ((';', 'latin1'), (',', 'latin1'), ('|', 'utf-8')):
        try:
            tmp = pl.read_csv(path, separator=sep, encoding=enc,
                              infer_schema_length=0, ignore_errors=True)
            if len(tmp.columns) > 5:
                df = tmp
                break
        except Exception:
            continue

    if df is None:
        log.warning(f'IRCA: no se pudo leer {path} con ningun separador.')
        return None

    df = df.rename({c: _normalize(c) for c in df.columns})
    rename = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    if rename:
        df = df.rename(rename)

    for col in ('anio', 'codigo_dep', 'codigo_mun', 'n_muestras',
                'n_muestras_urbano', 'n_muestras_rural'):
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Int32, strict=False))

    for col in ('promedio_irca', 'promedio_irca_urbano', 'promedio_irca_rural',
                'promedio_parametros', 'promedio_parametros_urbano', 'promedio_parametros_rural'):
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).str.replace(',', '.').cast(pl.Float64, strict=False))

    if 'anio' not in df.columns:
        log.warning('IRCA: columna anio no encontrada tras renombrado.')
        return None

    return df.filter(pl.col('anio').is_not_null())


def _register_duckdb(parquet_dir: Path, db_path: Path) -> None:
    glob = f'{parquet_dir.as_posix()}/irca_*.parquet'
    con = duckdb.connect(str(db_path))
    con.execute('DROP TABLE IF EXISTS irca')
    con.execute(f"CREATE TABLE irca AS SELECT * FROM read_parquet('{glob}')")
    n = con.execute('SELECT COUNT(*) FROM irca').fetchone()[0]
    con.close()
    print(f'  DuckDB [irca]: {n:,} filas')


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    raw_dir = base_dir / 'data' / 'raw'
    db_path = base_dir / 'data' / 'informe_regional.duckdb'
    parquet_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime('%Y_%m')
    parquet_path = parquet_dir / f'irca_{stamp}.parquet'

    if parquet_path.exists():
        print(f'irca_scraper: parquet existente {parquet_path}')
        _register_duckdb(parquet_dir, db_path)
        return

    # Check for manually dropped CSV files in data/raw/irca_manual/
    # Place any CSV downloaded from sivicap.ins.gov.co here and the scraper will pick it up.
    manual_dir = raw_dir / 'irca_manual'
    manual_dir.mkdir(exist_ok=True)
    manual_csvs = sorted(manual_dir.glob('*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
    if manual_csvs:
        src = manual_csvs[0]
        print(f'irca_scraper: usando archivo manual {src.name}')
        df = _parse_irca(src)
        if df is not None and not df.is_empty():
            df.write_parquet(parquet_path, compression='zstd')
            print(f'  -> {parquet_path} ({len(df):,} filas)')
            _register_duckdb(parquet_dir, db_path)
            print('irca_scraper OK')
            return
        print('irca_scraper: archivo manual no parseable, intentando SIVICAP...')

    with tempfile.TemporaryDirectory() as tmpdir:
        print('irca_scraper: conectando a SIVICAP...')
        downloaded = _scrape_sivicap(tmpdir)

        if downloaded is None:
            print('irca_scraper: ADVERTENCIA — no se pudo obtener datos de SIVICAP.')
            print('  Coloque el CSV descargado manualmente en data/raw/irca_manual/ y re-ejecute.')
            return

        print(f'irca_scraper: procesando {downloaded.name}')
        df = _parse_irca(downloaded)

    if df is None or df.is_empty():
        print('irca_scraper: ADVERTENCIA — no se pudo parsear el archivo descargado.')
        return

    df.write_parquet(parquet_path, compression='zstd')
    print(f'  -> {parquet_path} ({len(df):,} filas)')
    _register_duckdb(parquet_dir, db_path)
    print('irca_scraper OK')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run()
