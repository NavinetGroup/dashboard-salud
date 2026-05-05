# -*- coding: utf-8 -*-
"""
transform.py — Tidy all raw sources into Parquet + DuckDB.

For each source:
  1. Read raw CSV(s) from data/raw/ with Polars.
  2. Apply schema normalization.
  3. Write partitioned Parquet to data/parquet/<source>/.
  4. Register as a table in data/informe_regional.duckdb.

Run: python pipeline/transform.py
"""

import logging
from pathlib import Path

import duckdb
import polars as pl

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / 'data' / 'raw'
PARQUET_DIR = BASE_DIR / 'data' / 'parquet'
DB_PATH = BASE_DIR / 'data' / 'informe_regional.duckdb'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_parquet(df: pl.DataFrame, name: str) -> Path:
    out = PARQUET_DIR / f'{name}.parquet'
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out, compression='zstd')
    log.info(f'Parquet escrito: {out} ({len(df):,} filas)')
    return out


def _register_table(con: duckdb.DuckDBPyConnection, name: str, parquet_path: Path) -> None:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{parquet_path.as_posix()}')")
    count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    log.info(f'Tabla DuckDB [{name}]: {count:,} filas')


# ---------------------------------------------------------------------------
# Source: demografico — parquet written directly by scrapers/demografico.py
# ---------------------------------------------------------------------------

def transform_demografico(con: duckdb.DuckDBPyConnection) -> None:
    """Register pre-built demografico parquet files in DuckDB.
    The scraper (scrapers/demografico.py) writes the parquet directly;
    this function just ensures they are registered as DuckDB tables."""
    for name in ('demografico_edad_sexo', 'demografico_etnico'):
        path = PARQUET_DIR / f'{name}.parquet'
        if not path.exists():
            log.warning(f'demografico: {path.name} no encontrado — ejecuta scrapers/demografico.py primero.')
            continue
        _register_table(con, name, path)
        log.info(f'demografico: tabla [{name}] registrada desde parquet.')


# ---------------------------------------------------------------------------
# Source: IPS (Resumen_IPS_por_departamento.csv + IPS_intermedio.csv)
# ---------------------------------------------------------------------------

def transform_ips(con: duckdb.DuckDBPyConnection) -> None:
    resumen_files = sorted(RAW_DIR.glob('Resumen_IPS_por_departamento*.csv'))
    inter_files = sorted(RAW_DIR.glob('IPS_intermedio*.csv'))

    if not resumen_files and not inter_files:
        log.warning('IPS: no hay archivos en data/raw/. Omitiendo.')
        return

    # Summary table
    if resumen_files:
        frames = []
        for f in resumen_files:
            try:
                df = pl.read_csv(f, infer_schema_length=0)
                df = df.rename({c: c.strip() for c in df.columns})
                frames.append(df)
            except Exception as e:
                log.warning(f'IPS resumen: error leyendo {f} — {e}')
        if frames:
            df_res = pl.concat(frames, how='diagonal_relaxed').unique()
            # Normalize column names to snake_case
            rename = {}
            for c in df_res.columns:
                key = c.strip().lower().replace(' ', '_')
                if key != c:
                    rename[c] = key
            if rename:
                df_res = df_res.rename(rename)
            for col in ('total_ips', 'pública', 'privada', 'mixta'):
                if col in df_res.columns:
                    df_res = df_res.with_columns(pl.col(col).cast(pl.Int32, strict=False))
            parquet_path = _write_parquet(df_res, 'ips_resumen')
            _register_table(con, 'ips_resumen', parquet_path)

    # Intermediate (full detail)
    if inter_files:
        frames = []
        for f in inter_files:
            try:
                df = pl.read_csv(f, infer_schema_length=0, ignore_errors=True)
                frames.append(df)
            except Exception as e:
                log.warning(f'IPS intermedio: error leyendo {f} — {e}')
        if frames:
            df_int = pl.concat(frames, how='diagonal_relaxed').unique()
            parquet_path = _write_parquet(df_int, 'ips_detalle')
            _register_table(con, 'ips_detalle', parquet_path)


# ---------------------------------------------------------------------------
# Source: IRCA
# ---------------------------------------------------------------------------

def transform_irca(con: duckdb.DuckDBPyConnection) -> None:
    files = sorted(PARQUET_DIR.glob('irca*.parquet'))
    if not files:
        log.warning('irca: no hay parquet. Ejecuta scrapers/irca_scraper.py primero.')
        return
    glob = f'{PARQUET_DIR.as_posix()}/irca*.parquet'
    con.execute('DROP TABLE IF EXISTS irca')
    con.execute(f"CREATE TABLE irca AS SELECT * FROM read_parquet('{glob}')")
    n = con.execute('SELECT COUNT(*) FROM irca').fetchone()[0]
    log.info(f'Tabla DuckDB [irca]: {n:,} filas')


# ---------------------------------------------------------------------------
# Source: Afiliación — parquet written directly by scrapers/afiliacion_scraper.py
# ---------------------------------------------------------------------------

def transform_afiliacion(con: duckdb.DuckDBPyConnection) -> None:
    files = sorted(PARQUET_DIR.glob('afiliacion_*.parquet'))
    if not files:
        log.warning('afiliacion: no hay parquet. Ejecuta scrapers/afiliacion_scraper.py primero.')
        return
    glob = f'{PARQUET_DIR.as_posix()}/afiliacion_*.parquet'
    con.execute('DROP TABLE IF EXISTS afiliacion')
    con.execute(f"CREATE TABLE afiliacion AS SELECT * FROM read_parquet('{glob}')")
    n = con.execute('SELECT COUNT(*) FROM afiliacion').fetchone()[0]
    log.info(f'Tabla DuckDB [afiliacion]: {n:,} filas')


# ---------------------------------------------------------------------------
# Source: REPS (multi-endpoint)
# ---------------------------------------------------------------------------

REPS_ENDPOINTS = [
    'prestadores', 'sedes', 'servicios', 'capacidad', 'medidas_seguridad', 'sanciones'
]

def transform_reps(con: duckdb.DuckDBPyConnection) -> None:
    for ep in REPS_ENDPOINTS:
        files = sorted(PARQUET_DIR.glob(f'reps_{ep}_*.parquet'))
        if not files:
            log.warning(f'REPS [{ep}]: no hay parquet. Omitiendo.')
            continue
        glob = f'{PARQUET_DIR.as_posix()}/reps_{ep}_*.parquet'
        table = f'reps_{ep}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{glob}')")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        log.info(f'Tabla DuckDB [{table}]: {n:,} filas')


# ---------------------------------------------------------------------------
# Source: Supersalud (IPS / EPS intervenidas)
# ---------------------------------------------------------------------------

def transform_supersalud(con: duckdb.DuckDBPyConnection) -> None:
    for kind in ('ips_intervenidas', 'eps_intervenidas'):
        files = sorted(PARQUET_DIR.glob(f'supersalud_{kind}_*.parquet'))
        if not files:
            log.warning(f'Supersalud [{kind}]: no hay parquet. Omitiendo.')
            continue
        glob = f'{PARQUET_DIR.as_posix()}/supersalud_{kind}_*.parquet'
        table = f'supersalud_{kind}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{glob}')")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        log.info(f'Tabla DuckDB [{table}]: {n:,} filas')


# ---------------------------------------------------------------------------
# Source: INS PDF epidemiológico (todos los eventos)
# ---------------------------------------------------------------------------

INS_EVENTS = [
    'mortalidad_materna', 'sifilis_congenita', 'desnutricion_aguda',
    'mortalidad_menores5', 'dengue', 'intento_suicidio', 'violencia_genero',
]

def transform_ins_pdf(con: duckdb.DuckDBPyConnection) -> None:
    for event in INS_EVENTS:
        files = sorted(PARQUET_DIR.glob(f'ins_{event}_*.parquet'))
        if not files:
            log.warning(f'INS PDF [{event}]: no hay parquet. Omitiendo.')
            continue
        glob = f'{PARQUET_DIR.as_posix()}/ins_{event}_*.parquet'
        table = f'ins_{event}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{glob}', union_by_name=True)")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        log.info(f'Tabla DuckDB [{table}]: {n:,} filas')


# ---------------------------------------------------------------------------
# Source: DIFT18 Desempeño ET 2024
# ---------------------------------------------------------------------------

def transform_dift18(con: duckdb.DuckDBPyConnection) -> None:
    for name in ('dift18_departamento', 'dift18_municipio'):
        path = PARQUET_DIR / f'{name}.parquet'
        if not path.exists():
            log.warning(f'DIFT18 [{name}]: no hay parquet. Ejecuta scrapers/dift18_scraper.py primero.')
            continue
        _register_table(con, name, path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(base_dir: str = None) -> None:
    global BASE_DIR, RAW_DIR, PARQUET_DIR, DB_PATH
    if base_dir:
        BASE_DIR = Path(base_dir)
        RAW_DIR = BASE_DIR / 'data' / 'raw'
        PARQUET_DIR = BASE_DIR / 'data' / 'parquet'
        DB_PATH = BASE_DIR / 'data' / 'informe_regional.duckdb'

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)

    print(f'transform: conectando a {DB_PATH}')
    con = duckdb.connect(str(DB_PATH))

    try:
        print('transform: procesando demografico...')
        transform_demografico(con)

        print('transform: procesando REPS...')
        transform_reps(con)

        print('transform: procesando IPS legacy...')
        transform_ips(con)

        print('transform: procesando IRCA...')
        transform_irca(con)

        print('transform: procesando afiliacion...')
        transform_afiliacion(con)

        print('transform: procesando supersalud...')
        transform_supersalud(con)

        print('transform: procesando INS PDF...')
        transform_ins_pdf(con)

        print('transform: procesando DIFT18...')
        transform_dift18(con)

        tables = con.execute("SHOW TABLES").fetchall()
        print(f'\ntransform OK — tablas en DuckDB: {[t[0] for t in tables]}')

        print('\ntransform: normalizando geografía...')
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from scrapers import geo_normalize
        geo_normalize.build_all(DB_PATH)

        print('\ntransform: construyendo métricas consolidadas...')
        from pipeline import metricas
        metricas.build_all(DB_PATH)
    finally:
        con.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
