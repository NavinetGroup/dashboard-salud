# -*- coding: utf-8 -*-
"""
Scraper DANE Estadísticas Vitales — nacimientos y defunciones fetales por
municipio de residencia de la madre (denominador de la incidencia de sífilis
congénita, INS: casos ÷ (nacidos vivos + muertes fetales) × 1.000).

Fuente: los "cuadros unificados" anuales del DANE (Excel, sin autenticación),
uno por año en cada página:
  …/nacimientos/nacimientos-AAAA                  Cuadro 3: nacimientos por
                                                  municipio de residencia de la madre
  …/defunciones-fetales/defunciones-fetales-AAAA  Cuadro 6: defunciones fetales por
                                                  municipio de residencia de la madre
Solo se usan años completos (cifras definitivas o "año acumulado" cerrado); el
año corrido preliminar (≈ 6 meses, subregistrado) no sirve de denominador.

Salida: data/parquet/eevv_nacimientos_AAAA.parquet
  codigo_dep, codigo_mun (DIVIPOLA; DD999 = municipio sin información),
  nacimientos, defunciones_fetales, version (archivo de origen)
Filas con residencia en el exterior (75xxx) se excluyen; las de departamento
"sin información" (01999) se conservan para el total nacional.
"""

import logging
import os
import re
import tempfile
import time
import unicodedata
from datetime import date
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

DANE = 'https://www.dane.gov.co'
PAGES = {
    'nacimientos': '/index.php/estadisticas-por-tema/salud/nacimientos-y-defunciones/nacimientos/nacimientos-{y}',
    'defunciones_fetales': '/index.php/estadisticas-por-tema/salud/nacimientos-y-defunciones/'
                           'defunciones-fetales/defunciones-fetales-{y}',
}
# Sheet title fragments (normalised) identifying the by-residence table
TITLES = {
    'nacimientos': 'SEGUN DEPARTAMENTO Y MUNICIPIO DE RESIDENCIA DE LA MADRE',
    'defunciones_fetales': 'MUNICIPIO DE RESIDENCIA DE LA MADRE',
}
START_YEAR = 2024   # dashboard years 2025+ and their prior year; 2023 tables are protected .xls


def _norm(s) -> str:
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().upper()


def _get(s: requests.Session, url: str, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=(15, 300))
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                raise ScrapeError(f'eevv: 404 en {url}')
            log.warning(f'eevv: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'eevv: {type(e).__name__}, reintento {attempt + 1}/{retries}')
        time.sleep(10 * (attempt + 1))
    raise ScrapeError(f'eevv: sin respuesta de {url}')


def _full_year_link(s: requests.Session, kind: str, year: int) -> str | None:
    """URL of the year's closed-year table: 'definitivas' first, else a full-year
    'acumulado' that is not preliminary. None while only 'año corrido' exists."""
    html = _get(s, DANE + PAGES[kind].format(y=year)).text
    links = [(href, _norm(re.sub('<[^>]+>', '', text)))
             for href, text in re.findall(r'href="([^"]+\.xlsx?)"[^>]*>(.*?)</a>', html, re.S)]
    links = [(h, t) for h, t in links if str(year) in t]
    for test in (lambda t: 'DEFINITIV' in t,
                 lambda t: 'ACUMULADO' in t and f'{year}PR' not in t.replace(' ', '')):
        for href, text in links:
            if test(text):
                return href if href.startswith('http') else DANE + href
    return None


def _parse(content: bytes, kind: str, suffix: str) -> pl.DataFrame:
    # calamine detects legacy .xls (2023 tables) only from the file extension
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        sheets = pl.read_excel(path, sheet_id=0, engine='calamine', has_header=False,
                               infer_schema_length=0)
    finally:
        os.unlink(path)
    for name, raw in sheets.items():
        head = _norm(' '.join(str(v) for k in range(min(4, raw.height)) for v in raw.row(k) if v))
        if TITLES[kind] in head and ('AREA Y SEXO' in head or 'POR SEXO' in head):
            break
    else:
        raise ScrapeError(f'eevv: {kind}, ninguna hoja con "{TITLES[kind]}"')
    # Header row: the one with a 'Total' cell; its first 'Total' column is the count
    hdr = next(i for i in range(min(12, raw.height)) if any(_norm(v) == 'TOTAL' for v in raw.row(i)))
    tot = next(j for j, v in enumerate(raw.row(hdr)) if _norm(v) == 'TOTAL')
    code, count = raw.columns[1], raw.columns[tot]
    df = raw.slice(hdr + 1).filter(pl.col(code).str.contains(r'^\d{5}$'))
    if kind == 'defunciones_fetales':
        # one row per cause; the municipality total is labelled TOTAL / Total
        label = raw.columns[tot - 1]
        df = df.filter(pl.col(label).str.to_uppercase().str.strip_chars() == 'TOTAL')
    df = df.select(pl.col(code).alias('divipola'),
                   pl.col(count).cast(pl.Float64, strict=False).fill_null(0).cast(pl.Int64).alias(kind))
    return (df.filter(~pl.col('divipola').str.ends_with('000')          # national / department totals
                      & ~pl.col('divipola').str.starts_with('75'))      # residence abroad
              .group_by('divipola').agg(pl.col(kind).sum()))


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (informe-regional; Supersalud)'

    done = 0
    for year in range(START_YEAR, date.today().year + 1):
        out = parquet_dir / f'eevv_nacimientos_{year}.parquet'
        links = {k: _full_year_link(s, k, year) for k in PAGES}
        if not all(links.values()):
            log.info(f'eevv: {year} aún sin cifras de año completo')
            continue
        version = ' | '.join(u.rsplit('/', 1)[-1] for u in links.values())
        if out.exists() and pl.read_parquet(out, columns=['version'])['version'][0] == version:
            continue      # same files as last run (DANE replaces 'pr' with definitive later)
        parts = [_parse(_get(s, url).content, kind, Path(url).suffix) for kind, url in links.items()]
        df = (parts[0].join(parts[1], on='divipola', how='full', coalesce=True)
                      .with_columns(pl.col('nacimientos', 'defunciones_fetales').fill_null(0),
                                    pl.col('divipola').str.slice(0, 2).cast(pl.Int32).alias('codigo_dep'),
                                    pl.col('divipola').cast(pl.Int32).alias('codigo_mun'),
                                    pl.lit(year).alias('anio'), pl.lit(version).alias('version'))
                      .drop('divipola'))
        if df['nacimientos'].sum() < 300_000:
            raise ScrapeError(f'eevv: {year} con solo {df["nacimientos"].sum():,} nacimientos')
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        done += 1
        print(f'  -> {out.name} ({df.height:,} municipios, {df["nacimientos"].sum():,} nacimientos, '
              f'{df["defunciones_fetales"].sum():,} defunciones fetales)')
    print(f'eevv_scraper OK — {done} año(s) actualizado(s)')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
