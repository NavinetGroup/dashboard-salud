# -*- coding: utf-8 -*-
"""
Scraper BDUA — Base de Datos Única de Afiliados (ADRES / MSPS) en datos.gov.co.

Fuentes (Socrata, sin autenticación):
  d7a5-cnra  BDUA régimen subsidiado
  tq4m-hmg2  BDUA régimen contributivo
Cada dataset es una foto del mes vigente (1–2 M filas). No se descargan filas:
se agregan en el servidor (SoQL) a dos tablas pequeñas:

  bdua_eps_YYYY_MM.parquet       régimen × departamento × municipio × EPS → afiliados
  bdua_piramide_YYYY_MM.parquet  régimen × departamento × municipio × sexo × grupo de edad → afiliados

YYYY_MM es la fecha de actualización del dataset (rowsUpdatedAt). Como la fuente
solo publica el mes vigente, cada corrida archiva su foto: es la única forma de
tener serie histórica. pipeline/transform.py carga la foto más reciente.
"""

import logging
import time
from datetime import datetime
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

API = 'https://www.datos.gov.co'
DATASETS = {'subsidiado': 'd7a5-cnra', 'contributivo': 'tq4m-hmg2'}
PAGE = 50_000

# Aggregations: (output name, SoQL group columns → output column names)
_GEO = {'dpr_nombre': 'departamento', 'mnc_nombre': 'municipio'}
_QUERIES = {
    'eps':      {**_GEO, 'ent_id': 'ent_id', 'ent_nombre': 'ent_nombre'},
    'piramide': {**_GEO, 'tps_gnr_nombre': 'sexo', 'tps_grp_etr_id': 'grupo_edad'},
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers['User-Agent'] = 'informe-regional/1.0 (Supersalud)'
    return s


def _get(s: requests.Session, url: str, params: dict | None = None, retries: int = 4):
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=(15, 300))
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ScrapeError(f'bdua: HTTP {r.status_code} en {url}: {r.text[:200]}')
            log.warning(f'bdua: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'bdua: {e}, reintento {attempt + 1}/{retries}')
        time.sleep(15 * (attempt + 1))
    raise ScrapeError(f'bdua: sin respuesta de {url} tras {retries} intentos')


def _snapshot_date(s: requests.Session) -> datetime:
    """Both datasets are refreshed together; use the older update date, so the
    stamp never claims a month one of them doesn't have yet."""
    dates = []
    for ds in DATASETS.values():
        meta = _get(s, f'{API}/api/views/{ds}.json')
        dates.append(datetime.fromtimestamp(meta['rowsUpdatedAt']))
    return min(dates)


def _aggregate(s: requests.Session, regimen: str, ds: str, groups: dict) -> pl.DataFrame:
    cols = ', '.join(groups)
    rows, offset = [], 0
    while True:
        page = _get(s, f'{API}/resource/{ds}.json', {
            '$select': f'{cols}, sum(cantidad::number) AS afiliados',
            '$group': cols, '$order': cols, '$limit': PAGE, '$offset': offset,
        })
        rows += page
        if len(page) < PAGE:
            break
        offset += PAGE
    if not rows:
        raise ScrapeError(f'bdua: {ds} ({regimen}) no devolvió filas')
    df = pl.DataFrame(rows).rename(groups)
    return df.with_columns(
        pl.lit(regimen).alias('regimen'),
        pl.col('afiliados').cast(pl.Float64).cast(pl.Int64),
    )


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    s = _session()
    corte = _snapshot_date(s)
    stamp = f'{corte:%Y_%m}'
    outs = {name: parquet_dir / f'bdua_{name}_{stamp}.parquet' for name in _QUERIES}
    if all(p.exists() for p in outs.values()):
        print(f'bdua_scraper: foto {stamp} ya archivada.')
        return

    for name, groups in _QUERIES.items():
        frames = []
        for regimen, ds in DATASETS.items():
            df = _aggregate(s, regimen, ds, groups)
            log.info(f'BDUA [{name}/{regimen}]: {len(df):,} filas, {df["afiliados"].sum():,} afiliados')
            frames.append(df)
        df = pl.concat(frames).with_columns(pl.lit(corte.date()).alias('fecha_corte'))
        df.write_parquet(outs[name], compression='zstd', use_pyarrow=True)
        print(f'  -> {outs[name]} ({len(df):,} filas)')

    print(f'bdua_scraper OK — foto {corte:%Y-%m-%d}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
