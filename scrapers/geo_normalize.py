# -*- coding: utf-8 -*-
"""
Geographic normalization layer for all 19 DuckDB tables.

Builds:
  geo_maestro      — authoritative DANE reference (dep_codigo, mun_codigo, dep_dane, mun_dane)
  geo_dep          — distinct departments from geo_maestro (for dept-only joins)
  geo_map_<table>  — raw-name → DANE-code bridge for each name-based source
  v_<table>        — view over each source adding geo_dep_codigo, geo_mun_codigo,
                     geo_dep_dane, geo_mun_dane columns

Source of truth: demografico_edad_sexo (DANE PPED, ~11M rows, 1,122 unique municipalities).
"""

import logging
import re
import unicodedata
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

# Known normalized dept-name aliases → canonical normalized form
# Applied after accent-stripping + uppercase so both sides match the same key.
# Includes special district cities that report separately from their parent department.
DEPT_ALIASES: dict[str, str] = {
    # San Andrés variations
    'NORTE SANTANDER': 'NORTE DE SANTANDER',
    'SAN ANDRES Y PROVIDENCIA': 'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    'SAN ANDRES': 'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    'ARCH SAN ANDRES': 'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    'ARC SAN ANDRES': 'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    'ARCHIPIELAGO SAN ANDRES PROVIDENCIA Y SANTA CATALINA': 'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    # Bogotá
    'BOGOTA D C': 'BOGOTA D C',
    'BOGOTA': 'BOGOTA D C',
    'D C': 'BOGOTA D C',
    # Special districts — map to parent department
    'BARRANQUILLA': 'ATLANTICO',
    'CARTAGENA': 'BOLIVAR',
    'CALI': 'VALLE DEL CAUCA',
    'SANTA MARTA': 'MAGDALENA',
    'SANTA MARTA D E': 'MAGDALENA',
    'STA MARTA D E': 'MAGDALENA',
    'BUENAVENTURA': 'VALLE DEL CAUCA',
    # Abbreviated / alternate spellings
    'GUAJIRA': 'LA GUAJIRA',
    # Departmental capitals used as dept name in some Supersalud reports
    'IBAGUE': 'TOLIMA',
    'POPAYAN': 'CAUCA',
}

# (table, dept_col, mun_col, has_codes, dept_fallback_col)
# has_codes=True: dept_col / mun_col already hold integer DIVIPOLA codes.
# dept_fallback_col: used when dept_col is NULL (e.g. mixed dept/mun row tables).
GEO_SOURCES: list[tuple[str, str, str | None, bool, str | None]] = [
    ('demografico_edad_sexo',  'codigo_dep',          'codigo_mun',  True,  None),
    ('demografico_etnico',     'codigo_dep',          'codigo_mun',  True,  None),
    ('irca',                   'codigo_dep',          'codigo_mun',  True,  None),
    ('afiliacion',             'departamento',        'municipio',   False, None),
    ('reps_prestadores',       'depa_nombre',         'muni_nombre', False, None),
    ('reps_sedes',             'departamento',        'municipio',   False, None),
    ('reps_servicios',         'depa_nombre',         'muni_nombre', False, None),
    ('reps_capacidad',         'depa_nombre',         'muni_nombre', False, None),
    ('reps_medidas_seguridad', 'depa_nombre',         'muni_nombre', False, None),
    ('reps_sanciones',         'depa_nombre',         'muni_nombre', False, None),
    # ins_mortalidad_materna has dept-level rows (entidad_territorial) + mun rows (departamento/municipio)
    ('ins_mortalidad_materna', 'departamento',        'municipio',   False, 'entidad_territorial'),
    ('ins_sifilis_congenita',  'entidad_territorial', None,          False, None),
    ('ins_desnutricion_aguda', 'departamento',        'municipio',   False, None),
    ('ins_intento_suicidio',   'departamento',        'municipio',   False, None),
    ('ins_mortalidad_menores5','entidad_territorial', None,          False, None),
    ('ins_dengue',             'entidad_territorial', None,          False, None),
    ('ins_violencia_genero',   'entidad_territorial', None,          False, None),
    # supersalud: col_3 contains dept name; first data row has 'DEPARTAMENTO' (header artifact)
    # → maps to NULL dep_codigo, filtered out via WHERE geo_dep_codigo IS NOT NULL in queries
    ('supersalud_ips_intervenidas', 'col_3',       None,        False, None),
    ('supersalud_eps_intervenidas', 'col_3',       None,        False, None),
    # DIFT18: dept uses name column; mun already has integer DANE codes
    ('dift18_departamento',         'entidad_territorial', None, False, None),
    ('dift18_municipio',            'codigo_dep',  'codigo_mun', True,  None),
]


# ---------------------------------------------------------------------------
# Normalization key
# ---------------------------------------------------------------------------

def _normaliza(s) -> str:
    """Canonical matching key: uppercase, strip accents, collapse non-alphanum to space."""
    if not s:
        return ''
    s = str(s).upper().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Collapse spaced-letter encoding: "P U T U M A Y O" → "PUTUMAYO"
    tokens = s.split()
    if len(tokens) > 2 and all(len(t) == 1 for t in tokens):
        s = ''.join(tokens)
    return DEPT_ALIASES.get(s, s)


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

def _build_geo_maestro(con: duckdb.DuckDBPyConnection) -> None:
    """Build geo_maestro and geo_dep from demografico_edad_sexo."""
    # demografico codigo_mun is a string like '05001'; TRY_CAST drops leading zeros → 5001
    # irca codigo_mun is already an integer (5001)
    con.execute("""
        CREATE OR REPLACE TABLE geo_maestro AS
        SELECT DISTINCT
            CAST(codigo_dep AS INTEGER)      AS dep_codigo,
            TRY_CAST(codigo_mun AS INTEGER)  AS mun_codigo,
            nombre_dep                       AS dep_dane,
            municipio                        AS mun_dane
        FROM demografico_edad_sexo
        WHERE codigo_dep IS NOT NULL AND codigo_mun IS NOT NULL
    """)
    con.execute("""
        CREATE OR REPLACE TABLE geo_dep AS
        SELECT DISTINCT dep_codigo, dep_dane FROM geo_maestro
    """)
    n = con.execute("SELECT COUNT(*) FROM geo_maestro").fetchone()[0]
    print(f'  geo_maestro: {n:,} municipios únicos')


def _build_lookups(con: duckdb.DuckDBPyConnection) -> tuple[dict, dict]:
    rows = con.execute(
        "SELECT DISTINCT dep_codigo, mun_codigo, dep_dane, mun_dane FROM geo_maestro"
    ).fetchall()
    dep_lk: dict[str, int] = {}
    mun_lk: dict[tuple[int, str], int] = {}
    for dep_c, mun_c, dep_n, mun_n in rows:
        nk = _normaliza(dep_n)
        dep_lk.setdefault(nk, dep_c)
        mun_lk.setdefault((dep_c, _normaliza(mun_n)), mun_c)
    return dep_lk, mun_lk


# ---------------------------------------------------------------------------
# Mapping tables (name → code)
# ---------------------------------------------------------------------------

def _build_map_mun(con, table, dept_col, mun_col, dep_lk, mun_lk,
                   dept_fallback_col: str | None = None) -> None:
    """Bridge table for dept+mun name-based sources."""
    eff_dept = f"COALESCE({dept_col}, {dept_fallback_col})" if dept_fallback_col else dept_col
    pairs = con.execute(
        f"SELECT DISTINCT {eff_dept}, {mun_col} FROM {table}"
    ).fetchall()

    rows = []
    matched = 0
    for raw_dep, raw_mun in pairs:
        if raw_dep is None:
            continue
        nd = _normaliza(raw_dep)
        nm = _normaliza(raw_mun)
        dep_c = dep_lk.get(nd)
        mun_c = mun_lk.get((dep_c, nm)) if dep_c else None
        if mun_c:
            matched += 1
        rows.append((str(raw_dep), str(raw_mun) if raw_mun is not None else None, dep_c, mun_c))

    map_name = f'geo_map_{table}'
    con.execute(f"DROP TABLE IF EXISTS {map_name}")
    con.execute(f"""
        CREATE TABLE {map_name} (
            raw_dep   VARCHAR,
            raw_mun   VARCHAR,
            dep_codigo INTEGER,
            mun_codigo INTEGER
        )
    """)
    if rows:
        con.executemany(f"INSERT INTO {map_name} VALUES (?, ?, ?, ?)", rows)

    pct = 100 * matched / len(rows) if rows else 0
    print(f'  geo_map_{table}: {matched}/{len(rows)} municipios ({pct:.0f}% match)')


def _build_map_dep(con, table, dept_col, dep_lk) -> None:
    """Bridge table for dept-only name-based sources."""
    pairs = con.execute(
        f"SELECT DISTINCT {dept_col} FROM {table}"
    ).fetchall()

    rows = []
    matched = 0
    for (raw_dep,) in pairs:
        if raw_dep is None:
            continue
        nd = _normaliza(raw_dep)
        dep_c = dep_lk.get(nd)
        if dep_c:
            matched += 1
        rows.append((str(raw_dep), dep_c))

    map_name = f'geo_map_{table}'
    con.execute(f"DROP TABLE IF EXISTS {map_name}")
    con.execute(f"CREATE TABLE {map_name} (raw_dep VARCHAR, dep_codigo INTEGER)")
    if rows:
        con.executemany(f"INSERT INTO {map_name} VALUES (?, ?)", rows)

    pct = 100 * matched / len(rows) if rows else 0
    print(f'  geo_map_{table}: {matched}/{len(rows)} departamentos ({pct:.0f}% match)')


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _create_view_codes(con, table, dept_col, mun_col) -> None:
    """View for tables that already carry integer DIVIPOLA codes."""
    if mun_col:
        sql = f"""
            CREATE OR REPLACE VIEW v_{table} AS
            SELECT t.*,
                   CAST({dept_col} AS INTEGER)     AS geo_dep_codigo,
                   TRY_CAST({mun_col} AS INTEGER)  AS geo_mun_codigo,
                   gm.dep_dane                     AS geo_dep_dane,
                   gm.mun_dane                     AS geo_mun_dane
            FROM {table} t
            LEFT JOIN geo_maestro gm
                   ON CAST({dept_col} AS INTEGER)    = gm.dep_codigo
                  AND TRY_CAST({mun_col} AS INTEGER) = gm.mun_codigo
        """
    else:
        sql = f"""
            CREATE OR REPLACE VIEW v_{table} AS
            SELECT t.*,
                   CAST({dept_col} AS INTEGER)  AS geo_dep_codigo,
                   NULL::INTEGER                AS geo_mun_codigo,
                   gd.dep_dane                  AS geo_dep_dane,
                   NULL::VARCHAR                AS geo_mun_dane
            FROM {table} t
            LEFT JOIN geo_dep gd ON CAST({dept_col} AS INTEGER) = gd.dep_codigo
        """
    con.execute(sql)


def _create_view_names_mun(con, table, dept_col, mun_col,
                           dept_fallback_col: str | None = None) -> None:
    """View for name-based sources with dept + mun columns."""
    eff_dept = f"COALESCE(r.{dept_col}, r.{dept_fallback_col})" if dept_fallback_col else f"r.{dept_col}"
    sql = f"""
        CREATE OR REPLACE VIEW v_{table} AS
        SELECT r.*,
               mp.dep_codigo  AS geo_dep_codigo,
               mp.mun_codigo  AS geo_mun_codigo,
               gm.dep_dane    AS geo_dep_dane,
               gm.mun_dane    AS geo_mun_dane
        FROM {table} r
        LEFT JOIN geo_map_{table} mp
               ON {eff_dept}  IS NOT DISTINCT FROM mp.raw_dep
              AND r.{mun_col} IS NOT DISTINCT FROM mp.raw_mun
        LEFT JOIN geo_maestro gm
               ON mp.dep_codigo = gm.dep_codigo
              AND mp.mun_codigo  = gm.mun_codigo
    """
    con.execute(sql)


def _create_view_names_dep(con, table, dept_col) -> None:
    """View for name-based sources with dept-level data only."""
    sql = f"""
        CREATE OR REPLACE VIEW v_{table} AS
        SELECT r.*,
               mp.dep_codigo   AS geo_dep_codigo,
               NULL::INTEGER   AS geo_mun_codigo,
               gd.dep_dane     AS geo_dep_dane,
               NULL::VARCHAR   AS geo_mun_dane
        FROM {table} r
        LEFT JOIN geo_map_{table} mp
               ON r.{dept_col} IS NOT DISTINCT FROM mp.raw_dep
        LEFT JOIN geo_dep gd ON mp.dep_codigo = gd.dep_codigo
    """
    con.execute(sql)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_all(db_path: 'str | Path') -> None:
    """Build geo reference tables and normalized views in DuckDB."""
    print('geo_normalize: construyendo capa geográfica...')
    con = duckdb.connect(str(db_path))
    try:
        existing = {t[0] for t in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE'"
        ).fetchall()}

        if 'demografico_edad_sexo' not in existing:
            print('geo_normalize: ADVERTENCIA — demografico_edad_sexo no existe. Saltar.')
            return

        _build_geo_maestro(con)
        dep_lk, mun_lk = _build_lookups(con)

        n_views = 0
        for table, dept_col, mun_col, has_codes, dept_fallback in GEO_SOURCES:
            if table not in existing:
                log.info(f'geo_normalize: {table} no existe, saltando.')
                continue
            try:
                if has_codes:
                    _create_view_codes(con, table, dept_col, mun_col)
                elif mun_col:
                    _build_map_mun(con, table, dept_col, mun_col, dep_lk, mun_lk, dept_fallback)
                    _create_view_names_mun(con, table, dept_col, mun_col, dept_fallback)
                else:
                    _build_map_dep(con, table, dept_col, dep_lk)
                    _create_view_names_dep(con, table, dept_col)
                n_views += 1
            except Exception as e:
                log.warning(f'geo_normalize: error en {table} — {e}')

        print(f'geo_normalize OK — {n_views} vistas creadas')
    finally:
        con.close()


if __name__ == '__main__':
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format='%(levelname)s %(message)s')
    _base = Path(__file__).resolve().parent.parent
    build_all(_base / 'data' / 'informe_regional.duckdb')
