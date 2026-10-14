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
import re
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
    df.write_parquet(out, compression='zstd', use_pyarrow=True)
    log.info(f'Parquet escrito: {out} ({len(df):,} filas)')
    return out


def _register_table(con: duckdb.DuckDBPyConnection, name: str, parquet_path: Path) -> None:
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{parquet_path.as_posix()}')")
    count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    log.info(f'Tabla DuckDB [{name}]: {count:,} filas')


_SNAPSHOT_RE = re.compile(r'_(\d{4})_(\d{2})$')


def _register_latest_snapshot(con: duckdb.DuckDBPyConnection, prefix: str) -> None:
    """Load only the newest <prefix>_YYYY_MM.parquet into table <prefix>.

    REPS and Supersalud files are full point-in-time registers, not monthly
    increments: unioning them double-counts every provider/entity. The snapshot
    stamp is kept in a `snapshot` column so the dashboard can show the cut-off.
    """
    snapshots = sorted(
        (m.group(1) + '_' + m.group(2), p)
        for p in PARQUET_DIR.glob(f'{prefix}_*.parquet')
        if (m := _SNAPSHOT_RE.search(p.stem)) and p.stem == f'{prefix}_{m.group(1)}_{m.group(2)}'
    )
    if not snapshots:
        log.warning(f'[{prefix}]: no hay parquet. Omitiendo.')
        return
    stamp, path = snapshots[-1]
    con.execute(f'DROP TABLE IF EXISTS {prefix}')
    con.execute(f"CREATE TABLE {prefix} AS "
                f"SELECT *, '{stamp}' AS snapshot FROM read_parquet('{path.as_posix()}')")
    n = con.execute(f'SELECT COUNT(*) FROM {prefix}').fetchone()[0]
    log.info(f'Tabla DuckDB [{prefix}]: {n:,} filas (snapshot {stamp}; '
             f'{len(snapshots) - 1} anteriores ignorados)')


# ---------------------------------------------------------------------------
# Source: demografico — parquet written directly by scrapers/demografico.py
# ---------------------------------------------------------------------------

def transform_demografico(con: duckdb.DuckDBPyConnection) -> None:
    """Register demografico parquet files in DuckDB as pre-aggregated slim tables.

    The raw DANE PPED parquet has ~11.3M rows (per year × dep × mun × area × sexo × edad).
    No dashboard query uses `edad` or `area_geografica` (both are always summed over),
    so we collapse those two dimensions here. This drops the DB from ~410 MB to ~15 MB,
    enabling free-tier web hosting (Streamlit Cloud, etc.) without losing any information
    the dashboard actually reads. Raw parquets are preserved on disk for future use.
    """
    edad_sexo_path = PARQUET_DIR / 'demografico_edad_sexo.parquet'
    if edad_sexo_path.exists():
        con.execute('DROP TABLE IF EXISTS demografico_edad_sexo')
        con.execute(f"""
            CREATE TABLE demografico_edad_sexo AS
            SELECT codigo_dep, nombre_dep, codigo_mun, municipio,
                   anio, sexo,
                   SUM(poblacion) AS poblacion
            FROM read_parquet('{edad_sexo_path.as_posix()}')
            GROUP BY codigo_dep, nombre_dep, codigo_mun, municipio, anio, sexo
        """)
        # Under-5 population per municipality: denominator for the SIVIGILA
        # malnutrition indicators (the slim table above collapses age).
        con.execute('DROP TABLE IF EXISTS demografico_menores5')
        con.execute(f'''
            CREATE TABLE demografico_menores5 AS
            SELECT codigo_dep, codigo_mun, anio, SUM(poblacion) AS poblacion
            FROM read_parquet('{edad_sexo_path.as_posix()}')
            WHERE edad < 5
            GROUP BY codigo_dep, codigo_mun, anio
        ''')
        n = con.execute('SELECT COUNT(*) FROM demografico_edad_sexo').fetchone()[0]
        log.info(f'Tabla DuckDB [demografico_edad_sexo]: {n:,} filas (slim, edad+area colapsadas)')
    else:
        log.warning('demografico: demografico_edad_sexo.parquet no encontrado — ejecuta scrapers/demografico.py primero.')

    etnico_path = PARQUET_DIR / 'demografico_etnico.parquet'
    if etnico_path.exists():
        con.execute('DROP TABLE IF EXISTS demografico_etnico')
        con.execute(f"""
            CREATE TABLE demografico_etnico AS
            SELECT codigo_dep, nombre_dep, codigo_mun, municipio,
                   anio, grupo_etnico,
                   SUM(poblacion) AS poblacion
            FROM read_parquet('{etnico_path.as_posix()}')
            GROUP BY codigo_dep, nombre_dep, codigo_mun, municipio, anio, grupo_etnico
        """)
        n = con.execute('SELECT COUNT(*) FROM demografico_etnico').fetchone()[0]
        log.info(f'Tabla DuckDB [demografico_etnico]: {n:,} filas (slim, area colapsada)')
    else:
        log.warning('demografico: demografico_etnico.parquet no encontrado — ejecuta scrapers/demografico.py primero.')


# ---------------------------------------------------------------------------
# Source: IPS (Resumen_IPS_por_departamento.csv + IPS_intermedio.csv)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Source: SIVIGILA microdata — cases per week × residence municipality
# ---------------------------------------------------------------------------

def transform_sivigila(con: duckdb.DuckDBPyConnection) -> None:
    micro = sorted(PARQUET_DIR.glob('sivigila_casos_*.parquet'))
    prelim = sorted(PARQUET_DIR.glob('sivigila_rutinaria_*.parquet'))
    if not micro and not prelim:
        log.warning('sivigila: no hay parquet. Ejecuta scrapers/sivigila_scraper.py primero.')
        return
    con.execute('DROP TABLE IF EXISTS sivigila_casos')
    # Final microdata (one parquet per year) win; the weekly dashboard extract
    # ('rutinaria', preliminary) only fills years that have no microdata yet.
    parts = []
    if micro:
        parts.append(f"SELECT *, 'microdatos' AS fuente FROM read_parquet('{PARQUET_DIR.as_posix()}/sivigila_casos_*.parquet')")
    if prelim:
        excl = (f"WHERE anio NOT IN (SELECT DISTINCT anio FROM read_parquet("
                f"'{PARQUET_DIR.as_posix()}/sivigila_casos_*.parquet'))" if micro else '')
        parts.append(f"SELECT *, 'rutinaria' AS fuente FROM read_parquet("
                     f"'{PARQUET_DIR.as_posix()}/sivigila_rutinaria_*.parquet') {excl}")
    con.execute(f"""CREATE TABLE sivigila_casos AS
                    SELECT evento, anio, semana,
                           TRY_CAST(cod_dpto AS INTEGER) AS codigo_dep,
                           TRY_CAST(cod_mun AS INTEGER)  AS codigo_mun,
                           casos, fuente
                    FROM ({' UNION ALL BY NAME '.join(parts)})""")
    n, yrs = con.execute('SELECT COUNT(*), LIST(DISTINCT anio ORDER BY anio) FROM sivigila_casos').fetchone()
    fuentes = con.execute("SELECT LIST(DISTINCT anio || ':' || fuente ORDER BY anio || ':' || fuente) FROM sivigila_casos").fetchone()[0]
    log.info(f'Tabla DuckDB [sivigila_casos]: {n:,} filas ({fuentes})')


# ---------------------------------------------------------------------------
# Source: Financiamiento — CUIPO (ejecución por entidad) + SICODIS (asignación SGP)
# ---------------------------------------------------------------------------

def transform_financiamiento(con: duckdb.DuckDBPyConnection) -> None:
    for table, prefix, src in (('cuipo_salud', 'cuipo_salud_', 'cuipo_scraper'),
                               ('sgp_salud', 'sgp_salud_', 'sicodis_scraper'),
                               ('cofin_meta', 'cofin_meta_', 'cofinanciacion_scraper'),
                               ('cofin_lma', 'cofin_lma_', 'cofinanciacion_scraper'),
                               ('eevv_nacimientos', 'eevv_nacimientos_', 'eevv_scraper'),
                               ('ins_vsp', 'ins_vsp_', 'ins_vsp_scraper')):
        con.execute(f'DROP TABLE IF EXISTS {table}')
        if not list(PARQUET_DIR.glob(f'{prefix}*.parquet')):
            log.warning(f'{table}: no hay parquet. Ejecuta scrapers/{src}.py primero.')
            continue
        # One file per quarter (CUIPO), year (SICODIS, matriz) or month (LMA): no
        # overlap to dedupe. Co-financing files carry only the municipality code.
        dep = ', CAST(codigo_mun // 1000 AS INTEGER) AS codigo_dep' if prefix.startswith('cofin_') else ''
        if prefix == 'ins_vsp_':   # DD000 = departamento; districts carry their municipal code
            dep = (", CAST(CAST(codigo_entidad AS INTEGER) // 1000 AS INTEGER) AS codigo_dep, "
                   "CASE WHEN codigo_entidad LIKE '%000' THEN NULL "
                   "ELSE CAST(codigo_entidad AS INTEGER) END AS codigo_mun")
        con.execute(f"CREATE TABLE {table} AS SELECT *{dep} FROM read_parquet("
                    f"'{PARQUET_DIR.as_posix()}/{prefix}*.parquet', union_by_name=True)")
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        log.info(f'Tabla DuckDB [{table}]: {n:,} filas')


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
    # Each monthly SIVICAP export repeats earlier months, so dedupe on the natural
    # key (anio, mes, codigo_mun). The newest export wins: SIVICAP revises values,
    # and newer files use the current Resolución 622/2020 format. union_by_name
    # bridges the older Decreto 1575/2007 format (extra urbano/rural columns).
    con.execute(f"""
        CREATE TABLE irca AS
        SELECT * EXCLUDE (_rn, filename) FROM (
            SELECT *, ROW_NUMBER() OVER (
                       PARTITION BY anio, mes, codigo_mun ORDER BY filename DESC) AS _rn
            FROM read_parquet('{glob}', union_by_name=True, filename=True)
        ) WHERE _rn = 1
    """)
    n = con.execute('SELECT COUNT(*) FROM irca').fetchone()[0]
    log.info(f'Tabla DuckDB [irca]: {n:,} filas (deduplicadas)')


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
    # union_by_name: from 2026-03 MinSalud adds codigo_dep/codigo_mun (DIVIPOLA).
    # Without it DuckDB uses the first (oldest) file's schema and drops them.
    con.execute(f"CREATE TABLE afiliacion AS "
                f"SELECT * FROM read_parquet('{glob}', union_by_name=True)")
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
        _register_latest_snapshot(con, f'reps_{ep}')


# ---------------------------------------------------------------------------
# Source: Supersalud (IPS / EPS intervenidas)
# ---------------------------------------------------------------------------

def transform_supersalud(con: duckdb.DuckDBPyConnection) -> None:
    for kind in ('ips_intervenidas', 'eps_intervenidas'):
        _register_latest_snapshot(con, f'supersalud_{kind}')


# ---------------------------------------------------------------------------
# Source: BDUA (datos.gov.co) — monthly snapshot of affiliates by EPS / age / sex
# ---------------------------------------------------------------------------

def transform_bdua(con: duckdb.DuckDBPyConnection) -> None:
    for kind in ('eps', 'piramide'):
        _register_latest_snapshot(con, f'bdua_{kind}')


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
# Entry point
# ---------------------------------------------------------------------------

def run(base_dir: str = None, db_path: 'str | Path | None' = None) -> None:
    """Rebuild every table and view from data/parquet into db_path.

    db_path defaults to the live DB; pipeline/runner.py passes a separate build
    file and only publishes it after the quality checks pass.
    """
    global BASE_DIR, RAW_DIR, PARQUET_DIR, DB_PATH
    if base_dir:
        BASE_DIR = Path(base_dir)
        RAW_DIR = BASE_DIR / 'data' / 'raw'
        PARQUET_DIR = BASE_DIR / 'data' / 'parquet'
        DB_PATH = BASE_DIR / 'data' / 'informe_regional.duckdb'
    if db_path:
        DB_PATH = Path(db_path)

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)

    print(f'transform: conectando a {DB_PATH}')
    con = duckdb.connect(str(DB_PATH))

    try:
        print('transform: procesando demografico...')
        transform_demografico(con)

        print('transform: procesando REPS...')
        transform_reps(con)

        print('transform: procesando IRCA...')
        transform_irca(con)

        print('transform: procesando afiliacion...')
        transform_afiliacion(con)

        print('transform: procesando supersalud...')
        transform_supersalud(con)

        print('transform: procesando INS PDF...')
        transform_ins_pdf(con)

        print('transform: procesando BDUA...')
        transform_bdua(con)

        print('transform: procesando SIVIGILA...')
        transform_sivigila(con)

        print('transform: procesando financiamiento (CUIPO / SICODIS)...')
        transform_financiamiento(con)

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
