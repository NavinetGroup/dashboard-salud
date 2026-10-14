# -*- coding: utf-8 -*-
"""
Scraper SIVIGILA — microdatos anuales del INS (Portal SIVIGILA, SharePoint).

Reemplaza la lectura de los boletines PDF para los eventos cuyo conteo oficial
se reproduce desde los casos: una fila por caso, con municipio de residencia y
semana epidemiológica, para TODOS los municipios (el PDF solo lista algunos).

Fuente: https://portalsivigila.ins.gov.co/_api/web/lists/GetByTitle('Microdatos')
(REST sin autenticación). Un archivo Datos_<año>_<evento>.xlsx por evento y año;
el año en curso no se publica (los datos finales de un año salen ~agosto del
siguiente). El año corriente llegará por los tableros públicos del INS (fase 2).

Salida: data/parquet/sivigila_casos_<año>.parquet, agregado
    evento × anio × semana × cod_dpto × cod_mun → casos
Los xlsx crudos se conservan en data/raw/sivigila/ (hasta 110 MB cada uno) y se
reutilizan si el servidor no los ha modificado desde la descarga.

Mortalidad materna (550) NO está aquí: la razón oficial del INS usa criterios
clínicos que no están en los microdatos públicos (2025 sem ≤36: 276 casos en el
archivo vs 126 oficiales). Sigue viniendo del boletín PDF.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

PORTAL = 'https://portalsivigila.ins.gov.co'
LIST_URL = (f"{PORTAL}/_api/web/lists/GetByTitle('Microdatos')/items"
            "?$select=CodigoEvento,A_x00f1_o,NombreEvento,FileRef,Modified&$top=5000")

# SIVIGILA event codes → key used in table/column names
EVENTS = {
    '113': 'desnutricion_aguda',      # Desnutrición aguda en menores de 5 años
    '112': 'mortalidad_desnutricion', # Mortalidad por desnutrición (menores de 5)
    '220': 'dengue_grave',
    '356': 'intento_suicidio',
    '875': 'violencia_genero',        # Violencia de género e intrafamiliar
    '740': 'sifilis_congenita',
}
START_YEAR = 2023
COLUMNS = ['ANO', 'SEMANA', 'AJUSTE', 'COD_PAIS_R', 'COD_DPTO_R', 'COD_MUN_R']
# AJUSTE 6 = descartado, D = descartado por error de digitación
DESCARTADOS = ('6', 'D')
COLOMBIA = '170'


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': 'informe-regional/1.0 (Supersalud)',
                      'Accept': 'application/json;odata=verbose'})
    return s


def _get(s: requests.Session, url: str, retries: int = 4, **kw) -> requests.Response:
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=(15, 600), **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                raise ScrapeError(f'sivigila: 404 {url}')
            log.warning(f'sivigila: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'sivigila: {e}, reintento {attempt + 1}/{retries}')
        time.sleep(20 * (attempt + 1))
    raise ScrapeError(f'sivigila: sin respuesta de {url} tras {retries} intentos')


def list_files(s: requests.Session) -> list[dict]:
    """Every microdata file the portal lists: evento, anio, file_ref, modified."""
    items = []
    url = LIST_URL
    while url:
        data = _get(s, url).json()
        body = data.get('d', data)
        items += body.get('results', body.get('value', []))
        url = body.get('__next') or data.get('odata.nextLink')
    out = []
    for it in items:
        try:
            out.append({'evento': str(it['CodigoEvento']), 'anio': int(it['A_x00f1_o']),
                        'file_ref': it['FileRef'], 'modified': it['Modified']})
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise ScrapeError('sivigila: la lista de microdatos vino vacía')
    return out


def _download(s: requests.Session, file_ref: str, dest: Path, modified: str) -> Path:
    """Fetch the xlsx unless the cached copy is as new as the portal's Modified stamp."""
    meta = dest.with_suffix('.json')
    if dest.exists() and meta.exists():
        if json.loads(meta.read_text()).get('modified') == modified:
            return dest
    url = f"{PORTAL}/_api/Web/GetFileByServerRelativeUrl('{file_ref}')/$value"
    r = _get(s, url, stream=True)
    tmp = dest.with_suffix('.part')
    with open(tmp, 'wb') as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    meta.write_text(json.dumps({'modified': modified, 'downloaded': datetime.now(timezone.utc).isoformat()}))
    log.info(f'SIVIGILA: descargado {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)')
    return dest


def aggregate(path: Path, evento: str, anio: int) -> pl.DataFrame:
    """Valid cases per week and residence municipality (Colombia only)."""
    df = pl.read_excel(path, engine='calamine', infer_schema_length=0, columns=COLUMNS)
    df = df.filter(~pl.col('AJUSTE').is_in(DESCARTADOS))
    n_valid = df.height
    df = df.filter(pl.col('COD_PAIS_R') == COLOMBIA)
    df = df.filter(pl.col('ANO').cast(pl.Int32, strict=False) == anio)
    agg = (df.with_columns(
               pl.col('SEMANA').cast(pl.Int32, strict=False).alias('semana'),
               pl.col('COD_DPTO_R').str.zfill(2).alias('cod_dpto'),
               (pl.col('COD_DPTO_R').str.zfill(2) + pl.col('COD_MUN_R').str.zfill(3)).alias('cod_mun'))
             .group_by('semana', 'cod_dpto', 'cod_mun').len('casos')
             .with_columns(pl.lit(evento).alias('evento'), pl.lit(anio, dtype=pl.Int32).alias('anio'))
             .select('evento', 'anio', 'semana', 'cod_dpto', 'cod_mun', 'casos')
             .sort('semana', 'cod_mun'))
    log.info(f'SIVIGILA [{evento} {anio}]: {n_valid:,} casos válidos, '
             f'{agg["casos"].sum():,} residentes en Colombia, {agg.height:,} filas')
    return agg


def run(base_dir: str = None, start_year: int = START_YEAR) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    raw_dir = base_dir / 'data' / 'raw' / 'sivigila'
    parquet_dir = base_dir / 'data' / 'parquet'
    raw_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)

    s = _session()
    files = [f for f in list_files(s) if f['evento'] in EVENTS and f['anio'] >= start_year]
    by_year: dict[int, list[dict]] = {}
    for f in files:
        by_year.setdefault(f['anio'], []).append(f)
    if not by_year:
        raise ScrapeError(f'sivigila: ningún archivo desde {start_year} para los eventos {list(EVENTS)}')

    written, failed = [], []
    for anio in sorted(by_year):
        out = parquet_dir / f'sivigila_casos_{anio}.parquet'
        year_files = {f['evento']: f for f in by_year[anio]}
        # Rebuild the year if any of its files changed on the portal
        stamp = out.with_suffix('.json')
        current = {ev: f['modified'] for ev, f in sorted(year_files.items())}
        if out.exists() and stamp.exists() and json.loads(stamp.read_text()) == current:
            log.info(f'SIVIGILA {anio}: sin cambios, se conserva {out.name}')
            continue
        frames = []
        for ev, f in sorted(year_files.items()):
            try:
                path = _download(s, f['file_ref'], raw_dir / Path(f['file_ref']).name, f['modified'])
                frames.append(aggregate(path, ev, anio))
            except (ScrapeError, pl.exceptions.PolarsError, OSError) as e:
                log.error(f'SIVIGILA [{ev} {anio}]: {e}')
                failed.append(f'{ev}/{anio}')
        missing = set(EVENTS) - set(year_files)
        if missing:
            log.warning(f'SIVIGILA {anio}: el portal no lista los eventos {sorted(missing)}')
        if frames:
            df = pl.concat(frames)
            df.write_parquet(out, compression='zstd', use_pyarrow=True)
            stamp.write_text(json.dumps(current))
            written.append(out.name)
            print(f'  -> {out} ({df.height:,} filas, {df["casos"].sum():,} casos)')

    if failed:
        raise ScrapeError(f'sivigila: fallaron {", ".join(failed)}')
    print(f'sivigila_scraper OK — {len(written)} año(s) escritos, '
          f'años disponibles {min(by_year)}–{max(by_year)}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
