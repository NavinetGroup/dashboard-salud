# -*- coding: utf-8 -*-
"""
Scraper Supersalud:
  1. IPS intervenidas — Excel desde docs.supersalud.gov.co
  2. EPS intervenidas — Excel desde docs.supersalud.gov.co

Salidas:
  data/parquet/supersalud_ips_intervenidas_YYYY_MM.parquet
  data/parquet/supersalud_eps_intervenidas_YYYY_MM.parquet
"""

import io
import logging
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
import openpyxl
import polars as pl
import requests

log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

URL_IPS_XLSX = (
    'https://docs.supersalud.gov.co/PortalWeb/MedidasEspeciales/Directorio%20de%20Entidades/'
    'CTFT21-Listado-de-entidades-en-medida-preventiva-y-entidades-en-intervencion-forzosa-'
    'administrativa-para-administrar-IPS.xlsx'
)

URL_EPS_XLSX = (
    'https://docs.supersalud.gov.co/PortalWeb/MedidasEspeciales/Directorio%20de%20Entidades/'
    'CTFT21-Listado-de-entidades-en-medida-preventiva-y-entidades-en-intervencion-forzosa-'
    'administrativa-para-administrar-EPS.xlsx'
)


def _normalize_col(s: str) -> str:
    s = str(s).strip()
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', '_', s).lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9_]', '', s) or 'col'


def _read_excel_openpyxl(data: bytes) -> pl.DataFrame | None:
    """Read Excel using openpyxl, auto-detecting the header row."""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Find header row: first row with >= 3 non-null string values
    header_idx = 0
    for i, row in enumerate(all_rows):
        non_null = [v for v in row if v is not None and isinstance(v, str) and len(str(v).strip()) > 1]
        if len(non_null) >= 3:
            header_idx = i
            break

    headers_raw = all_rows[header_idx]
    headers = [_normalize_col(str(v)) if v is not None else f'col_{i}'
               for i, v in enumerate(headers_raw)]

    # Deduplicate
    seen: dict[str, int] = {}
    deduped = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            deduped.append(f'{h}_{seen[h]}')
        else:
            seen[h] = 0
            deduped.append(h)

    data_rows = []
    for row in all_rows[header_idx + 1:]:
        if all(v is None for v in row):
            continue
        cells = [str(v).strip() if v is not None else '' for v in row]
        padded = (cells + [''] * len(deduped))[:len(deduped)]
        data_rows.append(padded)

    if not data_rows:
        return None

    data_dict = {col: [r[i] for r in data_rows] for i, col in enumerate(deduped)}
    df = pl.DataFrame(data_dict)
    df = df.filter(~pl.all_horizontal(pl.col(c) == '' for c in deduped[:1]))
    return df if not df.is_empty() else None


def _scrape_xlsx(url: str, label: str, retries: int = 3) -> pl.DataFrame | None:
    """Download an Excel from Supersalud and return a tidy DataFrame."""
    content = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(10, 120),
                             stream=True, verify=False)
            if r.status_code != 200:
                log.warning(f'{label}: HTTP {r.status_code} — {url}')
                return None
            chunks = [c for c in r.iter_content(512 * 1024) if c]
            content = b''.join(chunks)
            break
        except Exception as e:
            if attempt < retries - 1:
                wait = 15 * (attempt + 1)
                log.warning(f'{label}: intento {attempt + 1} fallido, reintentando en {wait}s — {e}')
                time.sleep(wait)
            else:
                log.warning(f'{label}: {retries} intentos fallidos — {e}')
                return None

    try:
        raw = _read_excel_openpyxl(content)
        if raw is not None and not raw.is_empty():
            log.info(f'{label}: {len(raw):,} filas')
            return raw
    except Exception as e:
        log.warning(f'{label}: openpyxl fallo — {e}')

    return None


def _register_duckdb(parquet_dir: Path, db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    for kind in ('ips_intervenidas', 'eps_intervenidas'):
        files = sorted(parquet_dir.glob(f'supersalud_{kind}_*.parquet'))
        if not files:
            continue
        glob = f'{parquet_dir.as_posix()}/supersalud_{kind}_*.parquet'
        table = f'supersalud_{kind}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{glob}')")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'  DuckDB [{table}]: {n:,} filas')
    con.close()


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    db_path = base_dir / 'data' / 'informe_regional.duckdb'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime('%Y_%m')

    urls = {
        'ips_intervenidas': URL_IPS_XLSX,
        'eps_intervenidas': URL_EPS_XLSX,
    }

    for kind, url in urls.items():
        out = parquet_dir / f'supersalud_{kind}_{stamp}.parquet'
        if out.exists():
            print(f'supersalud_scraper: {kind} ya existe ({out}), omitiendo.')
            continue
        df = _scrape_xlsx(url, kind)
        if df is not None:
            df.write_parquet(out, compression='zstd')
            print(f'  -> {out} ({len(df):,} filas)')
        else:
            print(f'  -> {kind}: sin datos o error')

    _register_duckdb(parquet_dir, db_path)
    print('supersalud_scraper OK')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import urllib3
    urllib3.disable_warnings()
    run()
