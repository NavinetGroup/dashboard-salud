# -*- coding: utf-8 -*-
"""
Scraper afiliación en salud — MinSalud.

Descarga el ZIP mensual publicado en MinSalud, extrae el Excel interior,
lee la hoja CoberturaMunicipio y escribe Parquet (transform.py lo carga en DuckDB).
No produce archivos CSV intermedios.
"""

import io
import logging
import re
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

# Known historical URLs that don't match the standard pattern
HISTORICAL_URLS: dict[tuple[int, int], list[str]] = {
    (2025, 7):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-julio-2025.zip'],
    (2025, 8):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-agosto-2025.zip'],
    (2025, 9):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-septiembre-2025.zip'],
    (2025, 10): ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-oct2025.zip'],
    (2025, 11): ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/cifras-afiliacion-salud-nov-2025.zip'],
    (2025, 12): ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/cifras-afiliacion-salud-dic-2025.zip'],
    (2026, 1):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifra-afiliacion-salud-enero-2026.zip'],
    (2026, 2):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifras-afiliacion-salud-feb-2026.zip'],
    (2026, 3):  ['https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifras-afiliacion-salud-marzo-2026.zip'],
}

MESES_ES = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
    5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
    9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
}

RENAME_MAP = {
    'IdDepartamento': 'codigo_dep',
    'Departamento': 'departamento',
    'IdMunicipio': 'codigo_mun',
    'Municipio': 'municipio',
    'Contributivo': 'afiliados_contributivo',
    'Subsidiado': 'afiliados_subsidiado',
    'Total': 'afiliados_total',
    'DEPARTAMENTO': 'departamento',
    'MUNICIPIO': 'municipio',
    'REGIMEN': 'regimen',
    'Régimen': 'regimen',
    'ENTIDAD': 'entidad',
    'Entidad': 'entidad',
    'AFILIADOS': 'afiliados_total',
    'Afiliados': 'afiliados_total',
    'TOTAL AFILIADOS': 'afiliados_total',
    'Total Afiliados': 'afiliados_total',
    'CODIGO DEPARTAMENTO': 'codigo_dep',
    'CODIGO MUNICIPIO': 'codigo_mun',
    'Código Departamento': 'codigo_dep',
    'Código Municipio': 'codigo_mun',
}


# MinSalud has no stable naming scheme: verified 2026 files include
#   RBC/cifras-afiliacion-salud-abr-2026.zip, RBC/cifras-afiliacion-salud-jun-2026.zip,
#   DOA/cifras-afiliacion-salud-julio-2026.zip, RBC/cifras-afiliacion-salud-agosto2026.zip
# so candidates are probed (HEAD) in rough order of likelihood.
_URL_ROOT = 'https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/'
_URL_DIRS = ('RBC/', 'DOA/', 'DOA/OAS/')
_URL_STEMS = ('cifras-afiliacion-salud-{m}-{y}', 'cifras-afiliacion-salud-{m}{y}',
              'cifra-afiliacion-salud-{m}-{y}', 'cifras-afiliacion-{m}-{y}')
MESES_ABBR = {1: ('ene',), 2: ('feb',), 3: ('mar',), 4: ('abr',), 5: ('may',), 6: ('jun',),
              7: ('jul',), 8: ('ago',), 9: ('sep', 'sept'), 10: ('oct',), 11: ('nov',), 12: ('dic',)}


def _candidate_urls(year: int, month: int) -> list[str]:
    urls = list(HISTORICAL_URLS.get((year, month), []))
    names = (MESES_ES[month], *MESES_ABBR[month])
    for d in _URL_DIRS:
        for stem in _URL_STEMS:
            for n in names:
                u = _URL_ROOT + d + stem.format(m=n, y=year) + '.zip'
                if u not in urls:
                    urls.append(u)
    return urls


def _find_zip_url(year: int, month: int) -> str | None:
    """Return the first candidate URL that exists, or None if not published yet."""
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0'
    for url in _candidate_urls(year, month):
        try:
            r = session.head(url, timeout=(10, 30), allow_redirects=True)
        except requests.RequestException as e:
            log.warning(f'afiliacion: HEAD falló para {url} — {e}')
            continue
        if r.status_code == 200:
            return url
    return None


def _period_from_name(name: str) -> tuple[int, int] | None:
    """Read (year, month) from a name like 'CIFRAS MARZO-2026.xlsx' or '...-abr-2026.zip'."""
    s = name.lower()
    y = re.search(r'(20\d{2})', s)
    if not y:
        return None
    tokens = re.findall(r'[a-záéíóú]+', s)
    for month, full in MESES_ES.items():
        for t in tokens:
            if t == full or t in MESES_ABBR[month]:
                return int(y.group(1)), month
    return None


def _download_zip(url: str, retries: int = 3) -> bytes | None:
    headers = {'User-Agent': 'Mozilla/5.0'}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=(10, 300), stream=True)
            if r.status_code != 200:
                log.warning(f'afiliacion: HTTP {r.status_code} para {url}')
                return None
            chunks = [c for c in r.iter_content(1024 * 1024) if c]
            return b''.join(chunks)
        except Exception as e:
            if attempt < retries - 1:
                wait = 20 * (attempt + 1)
                log.warning(f'afiliacion: intento {attempt + 1} fallido, reintentando en {wait}s — {e}')
                time.sleep(wait)
            else:
                log.warning(f'afiliacion: {retries} intentos fallidos para {url} — {e}')
    return None


def _read_sheet_openpyxl(xlsx_bytes: bytes, sheet_name: str) -> list | None:
    """Read one sheet of an Excel file as a list of row tuples using openpyxl."""
    try:
        wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
        if sheet_name not in wb.sheetnames:
            wb.close()
            return None
        ws = wb[sheet_name]
        rows = [tuple(cell.value for cell in row) for row in ws.iter_rows()]
        wb.close()
        return rows
    except Exception as e:
        log.warning(f'afiliacion: error leyendo hoja {sheet_name} — {e}')
        return None


def _zip_inner_name(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(('.xlsx', '.xls'))]
            return names[0] if names else None
    except zipfile.BadZipFile:
        return None


def _extract_df_from_zip(data: bytes) -> pl.DataFrame | None:
    """Extract CoberturaMunicipio sheet from the MinSalud ZIP into a Polars DataFrame."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xlsx_names = [n for n in z.namelist() if n.lower().endswith(('.xlsx', '.xls'))]
            if not xlsx_names:
                log.warning('afiliacion: no hay Excel en el ZIP.')
                return None
            with z.open(xlsx_names[0]) as f:
                xlsx_bytes = f.read()
    except Exception as e:
        log.warning(f'afiliacion: error abriendo ZIP — {e}')
        return None

    preferred = ['CoberturaMunicipio', 'EPSMunicipio', 'EPS']
    for sheet in preferred:
        rows = _read_sheet_openpyxl(xlsx_bytes, sheet)
        if not rows:
            continue

        # Find the real header row: first row with ≥3 non-null string values
        header_idx = 0
        for i, row in enumerate(rows[:10]):
            non_null = [v for v in row if v is not None and str(v).strip()]
            if len(non_null) >= 3:
                header_idx = i
                break

        col_names = [str(v).strip() if v is not None else f'col_{j}'
                     for j, v in enumerate(rows[header_idx])]

        # Deduplicate column names
        seen: dict = {}
        deduped = []
        for c in col_names:
            if c not in seen:
                seen[c] = 0
                deduped.append(c)
            else:
                seen[c] += 1
                deduped.append(f'{c}.{seen[c]}')

        data_rows = rows[header_idx + 1:]
        n_cols = len(deduped)
        cols_dict = {
            deduped[j]: [str(row[j]).strip() if row[j] is not None else None
                         for row in data_rows if len(row) > j]
            for j in range(n_cols)
        }
        # Pad shorter columns
        max_len = max((len(v) for v in cols_dict.values()), default=0)
        for k in cols_dict:
            cols_dict[k] += [None] * (max_len - len(cols_dict[k]))

        df = pl.DataFrame(cols_dict)
        if df.is_empty():
            continue

        log.info(f'afiliacion: hoja [{sheet}] — {len(df):,} filas')
        return df

    log.warning('afiliacion: no se encontró ninguna hoja válida.')
    return None


def _normalize_df(df: pl.DataFrame, year: int, month: int) -> pl.DataFrame:
    df = df.rename({c: c.strip() for c in df.columns})
    df = df.rename({k: v for k, v in RENAME_MAP.items() if k in df.columns})

    df = df.with_columns([
        pl.lit(year).cast(pl.Int32).alias('anio'),
        pl.lit(MESES_ES[month].upper()).alias('mes'),
    ])

    for col in ('afiliados_total', 'afiliados_contributivo', 'afiliados_subsidiado', 'afiliados'):
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).str.replace_all(r'[,.]', '').cast(pl.Int64, strict=False)
            )

    df = df.filter(~pl.all_horizontal(pl.all().is_null()))
    return df


def _local_zip(base_dir: Path, year: int, month: int) -> Path | None:
    """A manually downloaded ZIP for this period, in the project root or data/raw."""
    for folder in (base_dir, base_dir / 'data' / 'raw'):
        for p in folder.glob('*.zip'):
            if 'afiliacion' in p.name.lower() and _period_from_name(p.name) == (year, month):
                return p
    return None


def _target_periods(year: int | None, month: int | None, lookback: int) -> list[tuple[int, int]]:
    if year is not None and month is not None:
        return [(year, month)]
    now = datetime.now()
    y, m = now.year, now.month
    periods = []
    for _ in range(lookback):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        periods.append((y, m))
    return periods


def run(base_dir: str = None, year: int = None, month: int = None, lookback: int = 12) -> None:
    """Fetch every month in the last `lookback` months that has no parquet yet.

    Data is always stored under the period stated inside the ZIP (the Excel is
    named e.g. 'CIFRAS MARZO-2026.xlsx'), never under the period we asked for:
    an unpublished month is simply skipped, not filled with a neighbour's data.
    """
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    def parquet_for(y: int, m: int) -> Path:
        return parquet_dir / f'afiliacion_{y}_{m:02d}.parquet'

    missing = [p for p in _target_periods(year, month, lookback) if not parquet_for(*p).exists()]
    if not missing:
        print('afiliacion_scraper: todos los meses ya están en parquet.')
        return

    written, unpublished, failed = [], [], []
    for y, m in missing:
        if parquet_for(y, m).exists():   # written earlier in this run under its true period
            continue
        local = _local_zip(base_dir, y, m)
        if local:
            log.info(f'afiliacion: usando ZIP local {local}')
            zip_data, source = local.read_bytes(), local.name
        else:
            url = _find_zip_url(y, m)
            if url is None:
                unpublished.append(f'{y}-{m:02d}')
                continue
            print(f'afiliacion_scraper: descargando {url}')
            zip_data, source = _download_zip(url), url
            if zip_data is None:
                log.warning(f'afiliacion: descarga fallida {url}')
                failed.append(f'{y}-{m:02d} (descarga)')
                continue

        inner = _zip_inner_name(zip_data)
        period = _period_from_name(inner or '') or _period_from_name(source)
        if period is None:
            log.warning(f'afiliacion: no se pudo leer el periodo de {source} ({inner}); omitido')
            failed.append(f'{y}-{m:02d} (periodo ilegible)')
            continue
        if period != (y, m):
            log.warning(f'afiliacion: {source} contiene {period[0]}-{period[1]:02d}, '
                        f'no {y}-{m:02d}; se guarda bajo su periodo real')
        out = parquet_for(*period)
        if out.exists():
            continue

        df = _extract_df_from_zip(zip_data)
        if df is None:
            log.warning(f'afiliacion: no se pudo leer el Excel de {source}')
            failed.append(f'{y}-{m:02d} (Excel ilegible)')
            continue
        df = _normalize_df(df, *period)
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        written.append(out.name)
        print(f'  -> {out} ({len(df):,} filas)')

    if unpublished:
        print(f'afiliacion_scraper: aún no publicados: {", ".join(unpublished)}')
    if failed:
        raise ScrapeError(f'afiliacion: fallaron {", ".join(failed)}')
    print(f'afiliacion_scraper OK — {len(written)} meses nuevos')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run()
