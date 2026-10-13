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
    'M4-FT-16-Listado-de-entidades-en-medida-preventiva-y-entidades-en-intervencion-forzosa-'
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


# Header label (normalized with _normalize_col, then prefix-matched) → canonical column.
# Both the IPS (M4-FT-16) and EPS (CTFT21) exports share this layout, with small
# label differences ("No." vs "NÚMERO", "Agente Interventor..." vs "REPRESENTANTE LEGAL").
_COLUMN_MAP: list[tuple[str, str]] = [
    ('no', 'numero'),
    ('numero', 'numero'),
    ('entidad', 'entidad'),
    ('ciudad', 'ciudad'),
    ('departamento', 'departamento'),
    ('nit', 'nit'),
    ('direccion', 'direccion'),
    ('clase_de_medida', 'clase_medida'),
    ('resolucion', 'resolucion'),
    ('fecha_final', 'fecha_final_medida'),
    ('acta_de_posesion', 'acta_posesion'),
    ('vencimiento', 'vencimiento_acta'),
]
_REQUIRED = ('entidad', 'departamento')


def _canonical(label: str) -> str | None:
    key = _normalize_col(label)
    for prefix, name in _COLUMN_MAP:
        if key == prefix or (len(prefix) > 2 and key.startswith(prefix)):
            return name
    return None


def _fecha_actualizacion(rows: list[tuple]) -> str | None:
    """The metadata row above the header reads '... Fecha de actualización | 31 de mayo de 2026'."""
    for row in rows:
        cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
        for i, c in enumerate(cells[:-1]):
            if _normalize_col(c).startswith('fecha_de_actualizacion'):
                return cells[i + 1]
    return None


def _parse_rows(all_rows: list[tuple]) -> pl.DataFrame | None:
    """Turn raw sheet rows into a tidy one-row-per-entity frame.

    The sheet starts with an 'Área responsable / Fecha de actualización' metadata
    row, then the real header, then data rows padded with blank numbered filler
    rows and a 'Nota:' footer. Personal data columns (representative names, ID
    numbers, e-mail, phone) are deliberately not kept.
    """
    header_idx = None
    for i, row in enumerate(all_rows):
        found = {_canonical(str(v)) for v in row if v is not None}
        if all(r in found for r in _REQUIRED):
            header_idx = i
            break
    if header_idx is None:
        log.warning('supersalud: no se encontró la fila de encabezado (ENTIDAD/DEPARTAMENTO)')
        return None

    col_idx: dict[str, int] = {}
    for j, v in enumerate(all_rows[header_idx]):
        name = _canonical(str(v)) if v is not None else None
        if name and name not in col_idx:
            col_idx[name] = j

    records = []
    for row in all_rows[header_idx + 1:]:
        def cell(name):
            j = col_idx.get(name)
            v = row[j] if j is not None and j < len(row) else None
            return re.sub(r'\s+', ' ', str(v)).strip() if v is not None else ''
        if not cell('entidad'):
            continue   # blank filler rows and the 'Nota:' footer
        records.append({name: cell(name) for name in col_idx})

    if not records:
        return None
    df = pl.DataFrame(records)
    return df.with_columns(pl.lit(_fecha_actualizacion(all_rows[:header_idx])).alias('fecha_actualizacion'))


def _read_excel_openpyxl(data: bytes) -> pl.DataFrame | None:
    """Read the Supersalud Excel with openpyxl (fastexcel can't decompress the IPS file)."""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        return _parse_rows(list(wb.active.iter_rows(values_only=True)))
    finally:
        wb.close()


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


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
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

    print('supersalud_scraper OK')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    import urllib3
    urllib3.disable_warnings()
    run()
