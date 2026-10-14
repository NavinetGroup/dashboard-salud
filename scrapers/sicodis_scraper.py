# -*- coding: utf-8 -*-
"""
Scraper SICODIS (DNP) — asignaciones del Sistema General de Participaciones.

El reporte nacional "SGP Resumen de Distribución" (Excel, sin autenticación)
trae una fila por entidad territorial con lo asignado en la vigencia por
participación. Se conservan las de salud:

  sgp_salud_AAAA.parquet   codigo_dep, codigo_mun (NULL = gobernación),
                           sgp_salud, sgp_regimen_subsidiado,
                           sgp_salud_publica, sgp_subsidio_oferta

Es el denominador de los indicadores de ejecución SGP de Financiamiento
(compromisos y pagos CUIPO ÷ asignación de la vigencia). Las vigencias
cerradas se descargan una vez; la vigente en cada corrida (el DNP añade
distribuciones parciales durante el año).
"""

import io
import logging
import time
from datetime import date
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

API = 'https://sicodis.dnp.gov.co/apiws/ApiSicodisNew'
START_YEAR = 2023
SHEET = 'Datos Reporte SGP Detalle'
_COLS = {
    'Codigo DANE Entidad': 'codigo_entidad',
    'Nombre Entidad': 'nombre_entidad',
    'Tipo Entidad': 'tipo_entidad',
    'Salud': 'sgp_salud',
    'Régimen Subsidiado': 'sgp_regimen_subsidiado',
    'Salud Pública': 'sgp_salud_publica',
    'Subsidio a la Oferta': 'sgp_subsidio_oferta',
}


def _get(s: requests.Session, url: str, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=(15, 180))
            if r.status_code == 200:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ScrapeError(f'sicodis: HTTP {r.status_code} en {url}: {r.text[:200]}')
            log.warning(f'sicodis: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'sicodis: {type(e).__name__}, reintento {attempt + 1}/{retries}')
        time.sleep(10 * (attempt + 1))
    raise ScrapeError(f'sicodis: sin respuesta de {url}')


def _year(s: requests.Session, year: int) -> pl.DataFrame:
    r = _get(s, f'{API}/sgp/archivo_resumen_participaciones/{year}/0/0/Todos/Todos')
    if r.content[:2] != b'PK':
        raise ScrapeError(f'sicodis: {year} no devolvió un Excel ({r.headers.get("content-type")})')
    raw = pl.read_excel(io.BytesIO(r.content), sheet_name=SHEET, engine='calamine', has_header=False)
    # A title block precedes the table: find the header row by its first cell.
    hdr = next((i for i, v in enumerate(raw.to_series(0).to_list()) if v == 'Región'), None)
    if hdr is None:
        raise ScrapeError(f'sicodis: {year} sin encabezado "Región" en la hoja {SHEET}')
    names = [str(v).strip() if v is not None else f'_c{j}' for j, v in enumerate(raw.row(hdr))]
    missing = [c for c in _COLS if c not in names]
    if missing:
        raise ScrapeError(f'sicodis: {year} sin columnas {missing}')
    df = raw.slice(hdr + 1).rename(dict(zip(raw.columns, names))).select(list(_COLS)).rename(_COLS)
    code = pl.col('codigo_entidad').str.strip_chars()
    df = df.filter(code.str.contains(r'^\d{5}$')).with_columns(
        pl.lit(year).alias('anio'),
        pl.col('nombre_entidad').str.strip_chars(),
        pl.col('tipo_entidad').str.strip_chars(),
        code.str.slice(0, 2).cast(pl.Int32).alias('codigo_dep'),
        # Gobernaciones carry DD000; Bogotá (11001) is listed once, as a municipio
        pl.when(code.str.ends_with('000')).then(None).otherwise(code.cast(pl.Int32)).alias('codigo_mun'),
        *[pl.col(c).cast(pl.Float64, strict=False) for c in _COLS.values() if c.startswith('sgp_')],
    )
    if df.height < 1000:
        raise ScrapeError(f'sicodis: {year} solo {df.height} entidades (se esperan ~1.130)')
    return df


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers['User-Agent'] = 'informe-regional/1.0 (Supersalud)'
    years = [int(r['anio']) for r in _get(s, f'{API}/sgp/vigencias').json()]
    current = max(y for y in years if y <= date.today().year)
    done = 0
    for year in sorted(y for y in years if START_YEAR <= y <= current):
        out = parquet_dir / f'sgp_salud_{year}.parquet'
        if out.exists() and year < current:
            continue
        df = _year(s, year)
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        done += 1
        print(f'  -> {out.name} ({df.height:,} entidades, SGP salud '
              f'${df["sgp_salud"].sum() / 1e12:,.2f} billones)')
    print(f'sicodis_scraper OK — {done} vigencia(s) descargada(s)')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
