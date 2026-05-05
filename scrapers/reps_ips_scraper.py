# -*- coding: utf-8 -*-
"""Scraper REPS (IPS por departamento) — lector tolerante."""

import os
import re
import time
import unicodedata
from pathlib import Path

import polars as pl
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

URL_LOGIN = 'https://prestadores.minsalud.gov.co/habilitacion/'
URL_CONSULTA = 'https://prestadores.minsalud.gov.co/habilitacion/consultas/habilitados_reps.aspx'


def quitar_tildes(s: str) -> str:
    s = s or ''
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def limpia_texto(s: str) -> str:
    if s is None:
        return ''
    s = str(s)
    s = s.replace('﻿', '').replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def esperar_descarga(desc_dir: str, objetivo_nombre: str, timeout: int = 180) -> str:
    print('Esperando descarga CSV...')
    t0 = time.time()
    tmp_path = None
    objetivo = os.path.join(desc_dir, objetivo_nombre)
    while True:
        archivos = os.listdir(desc_dir)
        if objetivo_nombre.lower() in [f.lower() for f in archivos]:
            return objetivo
        crs = [f for f in archivos if f.lower().endswith('.crdownload')]
        tmps = [f for f in archivos if f.lower().endswith('.tmp')]
        if crs:
            tmp_path = os.path.join(desc_dir, crs[0])
        elif tmps:
            tmp_path = os.path.join(desc_dir, tmps[0])
        if time.time() - t0 > timeout:
            if tmp_path and os.path.exists(tmp_path):
                os.rename(tmp_path, objetivo)
                return objetivo
            raise TimeoutError('La descarga no se completó en el tiempo previsto.')
        time.sleep(1)


def leer_csv_tolerante(path: str, sep: str = '|', encoding: str = 'latin1') -> pd.DataFrame:
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        header_line = f.readline().rstrip('\n\r').replace('﻿', '')
        raw_cols = header_line.split(sep)
        cols = [limpia_texto(c) for c in raw_cols]
        N = len(cols)
        rows = []
        for line in f:
            line = line.rstrip('\n\r')
            parts = line.split(sep)
            if len(parts) == N:
                rows.append(parts)
            elif len(parts) > N:
                rows.append(parts[:N - 1] + ['|'.join(parts[N - 1:])])
            else:
                rows.append(parts + [''] * (N - len(parts)))
    return pd.DataFrame(rows, columns=cols)


def normaliza_nat(x: str) -> str | None:
    base = quitar_tildes(limpia_texto(x)).lower()
    if base == 'publica':
        return 'Pública'
    if base == 'privada':
        return 'Privada'
    if base == 'mixta':
        return 'Mixta'
    return None


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    raw_dir = base_dir / 'data' / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    download_dir = str(raw_dir)

    # Limpiar archivos previos de REPS en raw_dir
    for f in os.listdir(download_dir):
        if f.lower() in ('prestadores.csv', 'ips_intermedio.csv') or \
                f.lower().endswith(('.tmp', '.crdownload')):
            try:
                os.remove(os.path.join(download_dir, f))
            except Exception:
                pass

    # Configurar Chrome
    chrome_options = Options()
    chrome_options.add_argument('--window-position=-32000,-32000')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--incognito')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'safebrowsing.enabled': True
    })

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 30)
    try:
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': download_dir
        })
    except Exception:
        pass

    print('Abriendo REPS login...')
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

    print('Realizando consulta REPS...')
    driver.get(URL_CONSULTA)
    time.sleep(2)
    wait.until(EC.element_to_be_clickable((By.ID, '_ctl0_ibBuscarFtr'))).click()
    time.sleep(5)

    sep_field = wait.until(EC.presence_of_element_located((By.ID, '_ctl0_ContentPlaceHolder1_tbSeparator')))
    driver.execute_script("arguments[0].value='|';", sep_field)
    time.sleep(1)

    print('Exportando CSV...')
    wait.until(EC.element_to_be_clickable((By.ID, '_ctl0_ContentPlaceHolder1_ibText'))).click()

    archivo_final = esperar_descarga(download_dir, 'Prestadores.csv', timeout=180)
    driver.quit()
    print(f'  -> descargado: {archivo_final}')

    # Procesar
    df = leer_csv_tolerante(archivo_final, sep='|', encoding='latin1')

    for c in ['depa_nombre', 'muni_nombre', 'clpr_nombre', 'naju_nombre']:
        if c in df.columns:
            df[c] = df[c].apply(limpia_texto)
    if 'depa_nombre' in df.columns:
        df['depa_nombre'] = df['depa_nombre'].str.title()
    if 'muni_nombre' in df.columns:
        df['muni_nombre'] = df['muni_nombre'].str.title()
    if 'clpr_codigo' in df.columns:
        df['clpr_codigo'] = pd.to_numeric(df['clpr_codigo'].apply(limpia_texto), errors='coerce')

    mask_codigo = df['clpr_codigo'] == 1 if 'clpr_codigo' in df.columns else pd.Series(False, index=df.index)
    mask_nombre = df['clpr_nombre'].str.contains('IPS', case=False, na=False) if 'clpr_nombre' in df.columns else pd.Series(False, index=df.index)
    ips = df[mask_codigo | mask_nombre].copy()

    out_int = raw_dir / 'IPS_intermedio.csv'
    ips.to_csv(out_int, index=False, encoding='utf-8')
    print(f'  -> {out_int}')

    if 'naju_nombre' in ips.columns:
        ips['naju_nombre'] = ips['naju_nombre'].apply(normaliza_nat)
    else:
        ips['naju_nombre'] = None

    if ips.empty:
        resumen = pd.DataFrame(columns=['depa_nombre', 'Total_IPS', 'Pública', 'Privada', 'Mixta'])
    else:
        tabla = pd.crosstab(ips['depa_nombre'], ips['naju_nombre'], dropna=True)
        for cat in ['Pública', 'Privada', 'Mixta']:
            if cat not in tabla.columns:
                tabla[cat] = 0
        tabla = tabla[['Pública', 'Privada', 'Mixta']].fillna(0).astype(int)
        tabla['Total_IPS'] = tabla.sum(axis=1)
        resumen = tabla.reset_index()[['depa_nombre', 'Total_IPS', 'Pública', 'Privada', 'Mixta']].sort_values('Total_IPS', ascending=False)

    out_res = raw_dir / 'Resumen_IPS_por_departamento.csv'
    resumen.to_csv(out_res, index=False, encoding='utf-8')
    print(f'  -> {out_res}')
    print('reps_ips_scraper OK')


if __name__ == '__main__':
    run()
