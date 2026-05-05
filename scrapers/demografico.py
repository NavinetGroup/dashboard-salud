# -*- coding: utf-8 -*-
"""
DANE demographics scraper — population by age/sex and ethnic/racial groups.

Reads Excel files from DANE, processes them in Python row-by-row, and writes
directly to Parquet + DuckDB (no intermediate CSV).
"""

import logging
import re
import time
import unicodedata
from io import BytesIO
from pathlib import Path

import duckdb
import openpyxl
import polars as pl
import requests

log = logging.getLogger(__name__)

URL_AGE = 'https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaSexoEdadMun-2018-2042_VP.xlsx'
URL_ETH = 'https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx'
SHEET_AGE = 'PobMunicipalxÁreaSexoEdad'
SHEET_ETH = 'Municipal'


def normalize_name(s) -> str:
    if s is None:
        return ''
    s = str(s)
    s = s.replace('﻿', '').replace('\xa0', ' ')
    s = unicodedata.normalize('NFKC', s)
    return ' '.join(s.split()).strip()


def _download(url: str, retries: int = 3) -> BytesIO:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=(10, 300), stream=True)
            r.raise_for_status()
            chunks = [c for c in r.iter_content(1024 * 1024) if c]
            return BytesIO(b''.join(chunks))
        except Exception as e:
            if attempt < retries - 1:
                wait = 20 * (attempt + 1)
                log.warning(f'demografico: intento {attempt + 1} fallido, reintentando en {wait}s — {e}')
                time.sleep(wait)
            else:
                raise


def _read_sheet(buf: BytesIO, sheet_name: str) -> list:
    """Read an Excel sheet as a list of row tuples via openpyxl (read-only stream)."""
    wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        rows = [tuple(cell.value for cell in row) for row in ws.iter_rows()]
    finally:
        wb.close()
    return rows


def _detect_header(rows, key_any=('DP', 'COD_DPTO', 'DEPARTAMENTO')):
    for i, row in enumerate(rows[:25]):
        vals = {normalize_name(v) for v in row}
        if vals & set(key_any):
            hr = i
            hr2 = None
            if i + 1 < len(rows):
                nxt = {normalize_name(v) for v in rows[i + 1]}
                if any(x.startswith('Hombres ') or x.startswith('Mujeres ') or x == 'Total'
                       for x in nxt):
                    hr2 = i + 1
            return hr, hr2
    raise RuntimeError('No header row found in DANE Excel.')


def _col_names(rows, hr, hr2):
    """Return fused column names from one or two header rows."""
    def _n(v):
        if v is None:
            return ''
        s = normalize_name(str(v))
        return '' if s.upper() in ('NONE', 'NAN') else s

    h1 = rows[hr]
    if hr2 is not None:
        h2 = rows[hr2]
        merged = [_n(b) if _n(b) else _n(a) for a, b in zip(h1, h2)]
    else:
        merged = [_n(x) for x in h1]

    # Deduplicate
    seen: dict = {}
    result = []
    for c in merged:
        name = c or None
        if name is None:
            result.append(None)
            continue
        if name not in seen:
            seen[name] = 0
            result.append(name)
        else:
            seen[name] += 1
            result.append(f'{name}.{seen[name]}')
    return result


def _write_parquet(df: pl.DataFrame, parquet_dir: Path, name: str) -> Path:
    out = parquet_dir / f'{name}.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out, compression='zstd')
    return out


def _register(con: duckdb.DuckDBPyConnection, name: str, path: Path) -> None:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path.as_posix()}')")
    n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f'  DuckDB [{name}]: {n:,} filas')


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    db_path = base_dir / 'data' / 'informe_regional.duckdb'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))

    # ------------------------------------------------------------------ #
    #  Edad / Sexo                                                         #
    # ------------------------------------------------------------------ #
    print('demografico: descargando proyecciones edad/sexo DANE...')
    try:
        rows_age = _read_sheet(_download(URL_AGE), SHEET_AGE)
    except Exception as e:
        print(f'  ERROR edad/sexo: {e}')
        con.close()
        return

    hr, hr2 = _detect_header(rows_age)
    cols = _col_names(rows_age, hr, hr2)
    start = (hr2 + 1) if hr2 is not None else (hr + 1)

    # Build column index maps
    id_map = {}
    pat = re.compile(r'^(Hombres|Mujeres)\s+(\d{1,3})', re.IGNORECASE)
    age_sex_cols = []  # list of (col_index, sex_upper, age_int)
    for i, c in enumerate(cols):
        if c is None:
            continue
        if c in ('DP', 'DPNOM', 'MPIO', 'DPMP', 'AÑO', 'ÁREA GEOGRÁFICA'):
            id_map[c] = i
        else:
            m = pat.match(c)
            if m:
                age_sex_cols.append((i, m.group(1).upper(), int(m.group(2))))

    if not age_sex_cols:
        print('  ERROR: no se detectaron columnas de edades.')
        con.close()
        return

    # Row-by-row melt — avoids Polars unpivot on 11M rows
    records_age = []
    for row in rows_age[start:]:
        dp_raw = row[id_map['DP']] if 'DP' in id_map else None
        try:
            dp = int(dp_raw)
        except (TypeError, ValueError):
            continue
        area = normalize_name(row[id_map.get('ÁREA GEOGRÁFICA', -1)] if 'ÁREA GEOGRÁFICA' in id_map else '')
        if 'total' in area.lower():
            continue
        anio_raw = row[id_map.get('AÑO', -1)] if 'AÑO' in id_map else None
        try:
            anio = int(anio_raw)
        except (TypeError, ValueError):
            continue
        dpnom = normalize_name(row[id_map.get('DPNOM', -1)] if 'DPNOM' in id_map else None)
        mpio  = str(row[id_map['MPIO']]) if 'MPIO' in id_map and row[id_map['MPIO']] is not None else None
        dpmp  = normalize_name(row[id_map.get('DPMP', -1)] if 'DPMP' in id_map else None)
        for col_idx, sex, age in age_sex_cols:
            pop_raw = row[col_idx] if col_idx < len(row) else None
            try:
                pop = int(pop_raw)
            except (TypeError, ValueError):
                continue
            records_age.append((dp, dpnom, mpio, dpmp, anio, area, sex, age, pop))

    print(f'  registros edad/sexo: {len(records_age):,}')
    df_age = pl.DataFrame(
        {
            'codigo_dep':       [r[0] for r in records_age],
            'nombre_dep':       [r[1] for r in records_age],
            'codigo_mun':       [r[2] for r in records_age],
            'municipio':        [r[3] for r in records_age],
            'anio':             [r[4] for r in records_age],
            'area_geografica':  [r[5] for r in records_age],
            'sexo':             [r[6] for r in records_age],
            'edad':             [r[7] for r in records_age],
            'poblacion':        [r[8] for r in records_age],
        },
        schema={
            'codigo_dep': pl.Int32,
            'nombre_dep': pl.Utf8,
            'codigo_mun': pl.Utf8,
            'municipio':  pl.Utf8,
            'anio':       pl.Int32,
            'area_geografica': pl.Utf8,
            'sexo':       pl.Utf8,
            'edad':       pl.Int32,
            'poblacion':  pl.Int64,
        }
    )
    path_age = _write_parquet(df_age, parquet_dir, 'demografico_edad_sexo')
    _register(con, 'demografico_edad_sexo', path_age)
    print(f'  -> {path_age}')

    # ------------------------------------------------------------------ #
    #  Étnico-racial                                                       #
    # ------------------------------------------------------------------ #
    print('demografico: descargando proyecciones étnico-raciales DANE...')
    try:
        rows_eth = _read_sheet(_download(URL_ETH), SHEET_ETH)
    except Exception as e:
        print(f'  ERROR étnico-racial: {e}')
        con.close()
        return

    hr_e, hr2_e = _detect_header(rows_eth, key_any=('COD_DPTO', 'DEPARTAMENTO', 'DP'))
    cols_e = _col_names(rows_eth, hr_e, hr2_e)
    start_e = (hr2_e + 1) if hr2_e is not None else (hr_e + 1)

    RENAME_ETH = {
        'COD_DPTO': 'DP', 'DEPARTAMENTO': 'DPNOM',
        'COD_DPTO-MPIO': 'MPIO', 'MUNICIPIO': 'DPMP',
        'AREA GEOGRAFICA': 'ÁREA GEOGRÁFICA',
        'Gitano(a) o Rrom': 'Gitana o Rrom',
        'Raizal del Archipiélago de San Andrés, Providencia y Santa Catalina': 'Raizal',
        'Palenquero(a) de San Basilio': 'Palenquera de San Basilio',
        'Negro(a), mulato(a), afrodescendiente, afrocolombiano(a)': 'Negra, mulata o afrocolombiana',
        'Ningún grupo étnico-racial': 'Ningún grupo',
    }
    ETHNIC_GROUPS = [
        'Indígena', 'Gitana o Rrom', 'Raizal', 'Palenquera de San Basilio',
        'Negra, mulata o afrocolombiana', 'Ningún grupo',
    ]
    cols_e_norm = [RENAME_ETH.get(c, c) if c else None for c in cols_e]

    id_map_e = {}
    eth_cols_idx = []  # (col_index, group_name)
    for i, c in enumerate(cols_e_norm):
        if c is None:
            continue
        if c in ('DP', 'DPNOM', 'MPIO', 'DPMP', 'AÑO', 'ÁREA GEOGRÁFICA'):
            id_map_e[c] = i
        elif c in ETHNIC_GROUPS:
            eth_cols_idx.append((i, c))

    if not eth_cols_idx:
        print('  ERROR: no se detectaron columnas étnicas.')
        con.close()
        return

    records_eth = []
    for row in rows_eth[start_e:]:
        dp_raw = row[id_map_e['DP']] if 'DP' in id_map_e else None
        try:
            dp = int(dp_raw)
        except (TypeError, ValueError):
            continue
        area = normalize_name(row[id_map_e['ÁREA GEOGRÁFICA']] if 'ÁREA GEOGRÁFICA' in id_map_e else '')
        if 'total' in area.lower():
            continue
        anio_raw = row[id_map_e.get('AÑO', -1)] if 'AÑO' in id_map_e else None
        try:
            anio = int(anio_raw)
        except (TypeError, ValueError):
            continue
        dpnom = normalize_name(row[id_map_e.get('DPNOM', -1)] if 'DPNOM' in id_map_e else None)
        mpio  = str(row[id_map_e['MPIO']]) if 'MPIO' in id_map_e and row[id_map_e['MPIO']] is not None else None
        dpmp  = normalize_name(row[id_map_e.get('DPMP', -1)] if 'DPMP' in id_map_e else None)
        for col_idx, grupo in eth_cols_idx:
            pop_raw = row[col_idx] if col_idx < len(row) else None
            try:
                pop = int(pop_raw)
            except (TypeError, ValueError):
                continue
            records_eth.append((dp, dpnom, mpio, dpmp, anio, area, grupo, pop))

    print(f'  registros étnico-racial: {len(records_eth):,}')
    df_eth = pl.DataFrame(
        {
            'codigo_dep':      [r[0] for r in records_eth],
            'nombre_dep':      [r[1] for r in records_eth],
            'codigo_mun':      [r[2] for r in records_eth],
            'municipio':       [r[3] for r in records_eth],
            'anio':            [r[4] for r in records_eth],
            'area_geografica': [r[5] for r in records_eth],
            'grupo_etnico':    [r[6] for r in records_eth],
            'poblacion':       [r[7] for r in records_eth],
        },
        schema={
            'codigo_dep':      pl.Int32,
            'nombre_dep':      pl.Utf8,
            'codigo_mun':      pl.Utf8,
            'municipio':       pl.Utf8,
            'anio':            pl.Int32,
            'area_geografica': pl.Utf8,
            'grupo_etnico':    pl.Utf8,
            'poblacion':       pl.Int64,
        }
    )
    path_eth = _write_parquet(df_eth, parquet_dir, 'demografico_etnico')
    _register(con, 'demografico_etnico', path_eth)
    print(f'  -> {path_eth}')

    con.close()
    print('demografico OK')


if __name__ == '__main__':
    run()
