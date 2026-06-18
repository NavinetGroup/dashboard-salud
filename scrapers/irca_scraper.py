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

# Persistent Chrome profile for SIVICAP. Run tools/setup_sivicap_session.py once
# to bootstrap a real-browser login (handles reCAPTCHA manually). Subsequent
# automated scrapes reuse the saved cookies and skip the login entirely.
PROFILE_DIR = Path(__file__).resolve().parent.parent / 'data' / 'chrome_profile_sivicap'

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


def _detect_chrome_major() -> int | None:
    """Return the installed Chrome major version from the Windows registry,
    or None on non-Windows / not installed. Auto-detect avoids hard-coding
    a version that breaks after Chrome auto-updates."""
    import subprocess
    try:
        out = subprocess.run(
            ['reg', 'query', r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon', '/v', 'version'],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            if 'version' in line.lower():
                ver = line.split()[-1]
                return int(ver.split('.')[0])
    except Exception:
        pass
    return None


def _make_driver(download_dir: str, headless: bool = True,
                 use_profile: bool = True) -> uc.Chrome:
    """Create a Chrome driver.

    headless: run without visible window (default). Set False for first-time
              setup so user can complete reCAPTCHA manually.
    use_profile: reuse the persistent SIVICAP profile if it exists. This carries
                 the session cookies from the manual login and skips reCAPTCHA
                 on subsequent runs.
    """
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
    major = _detect_chrome_major()
    # Pin version_main to match the installed Chrome — undetected-chromedriver's
    # default driver download can lag/lead the browser by one version, producing
    # "session not created" errors. Passing the exact major fixes the mismatch.
    kwargs = {'options': opts, 'headless': headless}
    if major:
        kwargs['version_main'] = major
    if use_profile:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        kwargs['user_data_dir'] = str(PROFILE_DIR)
    driver = uc.Chrome(**kwargs)
    try:
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': download_dir,
        })
    except Exception:
        pass
    return driver


def _is_logged_in(driver: uc.Chrome) -> bool:
    """Check whether the existing session is already authenticated by hitting a
    protected page — if SIVICAP doesn't redirect us to /Account/Login, we're in."""
    driver.get(SIVICAP_REPORT)
    time.sleep(3)
    return '/account/login' not in driver.current_url.lower()


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
    """Download IRCA monthly-per-municipality CSV from SIVICAP. Returns local path or None.

    Strategy:
      1. Open with persistent profile (cookies from previous manual login).
      2. Hit the report page directly; if SIVICAP doesn't redirect us to login,
         the session is still valid — skip the whole reCAPTCHA dance.
      3. Otherwise fall back to the (often-blocked) automated login.
    """
    driver = _make_driver(download_dir, headless=True, use_profile=True)
    try:
        wait = WebDriverWait(driver, 30)

        if _is_logged_in(driver):
            log.info(f'SIVICAP: sesión persistente válida ({driver.current_url})')
        else:
            log.info('SIVICAP: sesión no válida, intentando login automático...')
            if not _login(driver, wait):
                log.warning(
                    'SIVICAP: login automático rechazado (anti-bot). '
                    'Ejecute "python tools/setup_sivicap_session.py" UNA VEZ '
                    'para hacer login manual en el navegador y guardar la sesión.'
                )
                return None
            # _login already landed us on a post-login page; navigate to report
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
    # SIVICAP CSVs have trailing empty ;;;;; columns producing "_duplicated_N" /
    # unnamed columns. Drop anything that didn't map to a known field.
    known_cols = set(COLUMN_MAP.values())
    df = df.select([c for c in df.columns if c in known_cols])

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
    # Dedupe on natural key (anio, mes, codigo_mun). Monthly SIVICAP exports overlap
    # historical periods, so loading every parquet would duplicate rows. ROW_NUMBER
    # picks one row per key — all values for a given (anio, mes, mun) are identical
    # across exports. union_by_name handles the schema gap between the older
    # Decreto 1575/2007 format (has urbano/rural columns) and the newer
    # Resolución 622/2020 format (consolidated columns only).
    con.execute(f"""
        CREATE TABLE irca AS
        SELECT * EXCLUDE (_rn) FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY anio, mes, codigo_mun ORDER BY anio) AS _rn
            FROM read_parquet('{glob}', union_by_name=True)
        ) WHERE _rn = 1
    """)
    n = con.execute('SELECT COUNT(*) FROM irca').fetchone()[0]
    con.close()
    print(f'  DuckDB [irca]: {n:,} filas (deduplicadas)')


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
