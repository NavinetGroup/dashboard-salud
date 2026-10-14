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

# Department-name aliases → DIVIPOLA dept code.
# Keys are normalized with _key() (uppercase, no accents, alphanumerics only).
# Aliases point at codes rather than canonical names, so an alias can never
# silently miss because DANE spells the target differently.
# Applied to department names only — never to municipality names.
DEPT_ALIASES: dict[str, int] = {
    'NORTE SANTANDER': 54,
    'NORTE DE SANTAN': 54,   # truncated in INS PDF tables
    'VALLE': 76,
    'GUAJIRA': 44,
    'BOGOTA': 11,
    'BOGOTA D C': 11,
    'D C': 11,
    'SAN ANDRES': 88,
    'SAN ANDRES Y PROVIDENCIA': 88,
    'SAN ANDRES PROVIDENCIA Y SANTA CATALINA': 88,
    'ARCH SAN ANDRES': 88,
    'ARC SAN ANDRES': 88,
    'ARCHIPIELAGO SAN ANDRES PROVIDENCIA Y SANTA CATALINA': 88,
    # Departmental capitals used as dept name in some Supersalud reports
    'IBAGUE': 73,
    'POPAYAN': 19,
}

# Special districts that INS / REPS / DIFT report as if they were departments.
# Dept-level lookups resolve them to the parent department; views also expose
# the district's own municipality code in geo_distrito_codigo so aggregations
# can tell a district row apart from the department row.
DISTRICTS: dict[str, int] = {
    'BARRANQUILLA': 8001,
    'CARTAGENA': 13001,
    'CARTAGENA DE INDIAS': 13001,
    'SANTA MARTA': 47001,
    'SANTA MARTA D E': 47001,
    'STA MARTA D E': 47001,
    'CALI': 76001,
    'SANTIAGO DE CALI': 76001,
    'BUENAVENTURA': 76109,
}

# Municipality-name aliases, scoped by dept code → DIVIPOLA municipality code.
# Only spellings verified against geo_maestro and the REPS habilitation-code
# prefix belong here; never add fuzzy guesses (Antioquia has both San Pedro de
# Los Milagros and San Pedro de Urabá).
MUN_ALIASES: dict[tuple[int, str], int] = {
    (11, 'BOGOTA'): 11001,
    (13, 'CARTAGENA'): 13001,
    (13, 'SANTA CRUZ DE MOMPOX'): 13468,
    (54, 'CUCUTA'): 54001,
    (52, 'TUMACO'): 52835,
    (52, 'CUASPUD'): 52224,
    (76, 'SANTIAGO DE CALI'): 76001,
    (5, 'SAN PEDRO'): 5664,
    (5, 'SAN ANDRES'): 5647,
    (5, 'DON MATIAS'): 5237,
    (5, 'SANTA FE DE ANTIOQUIA'): 5042,
    (5, 'SAN VICENTE FERRER'): 5674,
    (15, 'GUICAN'): 15332,
    (19, 'PIENDAMO'): 19548,
    (19, 'LOPEZ'): 19418,
    (19, 'SOTARA'): 19760,
    (20, 'MANAURE'): 20443,
    (23, 'PURISIMA'): 23586,
    (23, 'SAN ANDRES DE SOTAVENTO'): 23670,
    (25, 'SAN JUAN DE RIO SECO'): 25662,
    (27, 'BELEN DE BAJIRA'): 27493,
    (47, 'CERRO SAN ANTONIO'): 47161,
    (47, 'CHIVOLO'): 47170,
    (70, 'SINCE'): 70742,
    (70, 'SAN JOSE DE TOLUVIEJO'): 70823,
    (73, 'SAN SEBASTIAN DE MARIQUITA'): 73443,
    (86, 'LEGUIZAMO'): 86573,
    (94, 'BARRANCO MINAS'): 94343,
    (97, 'PAPUNAUA'): 97777,
    # BDUA (datos.gov.co) spellings, verified 2026-10-13
    (91, 'MIRITINPARANA'): 91460,
    (91, 'PTO SANTANDER'): 91669,
    (5, 'ANTIOQUIA'): 5042,             # Santa Fe de Antioquia
    (5, 'BOLIVAR'): 5101,               # Ciudad Bolívar
    (5, 'CARMEN DE VIBORAL'): 5148,
    (5, 'SANTUARIO'): 5697,
    (8, 'POLO NUEVO'): 8558,
    (15, 'TUTASA'): 15839,
    (17, 'SAN JOSE DE CALDAS'): 17665,
    (18, 'SAN JOSE DE FRAGUA'): 18610,
    (19, 'PATIA EL BORDO'): 19532,
    (20, 'CODAZZI'): 20013,
    (20, 'LA PAZ ROBLES'): 20621,
    (25, 'EL PENOL'): 25258,            # El Peñón (Cundinamarca)
    (25, 'S ANTONIO TEQUENDAMA'): 25645,
    (25, 'UBATE'): 25843,               # Villa de San Diego de Ubaté
    (27, 'CANTON DE SAN PABLO'): 27135,
    (27, 'EL CARMEN'): 27245,           # El Carmen de Atrato
    (27, 'ITSMINA'): 27361,
    (47, 'SABANA DE SAN ANGEL'): 47660,
    (47, 'SAN SEBASTIAN BUENAVIST'): 47692,
    (50, 'LA URIBE'): 50370,
    (50, 'SAN CARLOS GUAROA'): 50680,
    (50, 'VISTA HERMOSA'): 50711,
    (52, 'EL TABLON'): 52258,           # El Tablón de Gómez
    (52, 'FRANCIS PIZARRO'): 52520,
    (52, 'LEYVA'): 52405,
    (66, 'DOS QUEBRADAS'): 66170,
    (68, 'EL CARMEN'): 68235,           # El Carmen de Chucurí
    (70, 'TOLU'): 70820,                # Santiago de Tolú (not Tolú Viejo)
    (70, 'TOLUVIEJO'): 70823,
    (73, 'GUAYABAL'): 73055,            # Armero (Guayabal)
    (73, 'VILLA HERMOSA'): 73870,
    (76, 'BUGA'): 76111,                # Guadalajara de Buga
    (47, 'EL PIJINO DEL CARMEN'): 47545,  # Pijiño del Carmen
    (94, 'MORICHAL NUEVO'): 94888,
}

# Sources that carry a DIVIPOLA municipality code: the code wins, and name
# matching is only the fallback for rows where it is missing or invalid.
# (table, SQL expression over the row alias r yielding the code, dept_col, mun_col)
#
# REPS: the first 5 digits of the 10-digit codigo_habilitacion are the DIVIPOLA
# municipality code. Verified 2026-10-13: it agrees with name matching on every
# row except the Buenaventura→Cali mis-match, and resolves Cartagena, Cúcuta,
# Tumaco, etc. that names miss.
# Afiliación: MinSalud added codigo_mun to the ZIP from March 2026; earlier
# months have no code column (NULL after union_by_name) and use names.
_REPS_CODE = "LEFT(LPAD(CAST(r.codigo_habilitacion AS VARCHAR), 10, '0'), 5)"
CODE_FIRST_SOURCES: list[tuple[str, str, str, str]] = [
    ('reps_prestadores',       _REPS_CODE,     'depa_nombre',  'muni_nombre'),
    ('reps_sedes',             _REPS_CODE,     'departamento', 'municipio'),
    ('reps_servicios',         _REPS_CODE,     'depa_nombre',  'muni_nombre'),
    ('reps_capacidad',         _REPS_CODE,     'depa_nombre',  'muni_nombre'),
    ('reps_medidas_seguridad', _REPS_CODE,     'depa_nombre',  'muni_nombre'),
    ('reps_sanciones',         _REPS_CODE,     'depa_nombre',  'muni_nombre'),
    ('afiliacion',             'r.codigo_mun', 'departamento', 'municipio'),
]

# (table, dept_col, mun_col, has_codes, dept_fallback_col)
# has_codes=True: dept_col / mun_col already hold integer DIVIPOLA codes.
# dept_fallback_col: used when dept_col is NULL (e.g. mixed dept/mun row tables).
GEO_SOURCES: list[tuple[str, str, str | None, bool, str | None]] = [
    ('demografico_edad_sexo',  'codigo_dep',          'codigo_mun',  True,  None),
    ('demografico_etnico',     'codigo_dep',          'codigo_mun',  True,  None),
    ('irca',                   'codigo_dep',          'codigo_mun',  True,  None),
    ('sivigila_casos',         'codigo_dep',          'codigo_mun',  True,  None),
    ('demografico_menores5',   'codigo_dep',          'codigo_mun',  True,  None),
    ('cuipo_salud',            'codigo_dep',          'codigo_mun',  True,  None),   # gobernaciones: codigo_mun NULL
    ('cofin_meta',             'codigo_dep',          'codigo_mun',  True,  None),
    ('cofin_lma',              'codigo_dep',          'codigo_mun',  True,  None),
    ('eevv_nacimientos',       'codigo_dep',          'codigo_mun',  True,  None),   # DD999 = mun. sin información
    ('ins_vsp',                'codigo_dep',          'codigo_mun',  True,  None),   # departments + districts
    # afiliacion and reps_* are handled via CODE_FIRST_SOURCES
    ('bdua_eps',               'departamento',        'municipio',   False, None),
    ('bdua_piramide',          'departamento',        'municipio',   False, None),
    # ins_mortalidad_materna has dept-level rows (entidad_territorial) + mun rows (departamento/municipio)
    ('ins_mortalidad_materna', 'departamento',        'municipio',   False, 'entidad_territorial'),
    ('ins_sifilis_congenita',  'entidad_territorial', None,          False, None),
    ('ins_desnutricion_aguda', 'departamento',        'municipio',   False, None),
    ('ins_intento_suicidio',   'departamento',        'municipio',   False, None),
    ('ins_mortalidad_menores5','entidad_territorial', None,          False, None),
    ('ins_dengue',             'entidad_territorial', None,          False, None),
    ('ins_violencia_genero',   'entidad_territorial', None,          False, None),
    # supersalud: some rows have ciudad/departamento swapped (e.g. 'TOLIMA' / 'IBAGUÉ');
    # the capital-city entries in DEPT_ALIASES resolve those.
    ('supersalud_ips_intervenidas', 'departamento', None,       False, None),
    ('supersalud_eps_intervenidas', 'departamento', None,       False, None),
]


# ---------------------------------------------------------------------------
# Normalization key
# ---------------------------------------------------------------------------

# Trailing tokens that mark non-municipalized areas: DANE writes "(ANM)",
# INS writes "(CD)" (corregimiento departamental), afiliación writes neither.
_AREA_SUFFIXES = (' ANM', ' CD')


def _key(s) -> str:
    """Canonical matching key: uppercase, strip accents, collapse non-alphanum to space."""
    if not s:
        return ''
    # BDUA exports carry a mis-encoded Ñ as '¥' ('PUERTO NARI¥O')
    s = str(s).upper().strip().replace('¥', 'Ñ')
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Collapse spaced-letter encoding: "P U T U M A Y O" → "PUTUMAYO"
    tokens = s.split()
    if len(tokens) > 2 and all(len(t) == 1 for t in tokens):
        s = ''.join(tokens)
    for suffix in _AREA_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _dep_code(raw, dep_lk: dict[str, int]) -> int | None:
    k = _key(raw)
    if k in dep_lk:
        return dep_lk[k]
    if k in DEPT_ALIASES:
        return DEPT_ALIASES[k]
    if k in DISTRICTS:
        return DISTRICTS[k] // 1000
    # PDF extraction sometimes splits words at random ("N o r t e d e S antander"),
    # which the spaced-letter rule in _key() can't undo; compare without spaces.
    nospace = k.replace(' ', '')
    for name, code in (*dep_lk.items(), *DEPT_ALIASES.items()):
        if name.replace(' ', '') == nospace:
            return code
    return None


def _mun_code(dep_c: int | None, raw, mun_lk: dict[tuple[int, str], int]) -> int | None:
    if dep_c is None:
        return None
    k = _key(raw)
    return mun_lk.get((dep_c, k)) or MUN_ALIASES.get((dep_c, k))


def _distrito_code(raw) -> int | None:
    return DISTRICTS.get(_key(raw))


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
        dep_lk.setdefault(_key(dep_n), dep_c)
        k = (dep_c, _key(mun_n))
        if k in mun_lk and mun_lk[k] != mun_c:
            raise ValueError(f'geo_maestro: clave de municipio ambigua {k}')
        mun_lk[k] = mun_c
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
        dep_c = _dep_code(raw_dep, dep_lk)
        mun_c = _mun_code(dep_c, raw_mun, mun_lk)
        if mun_c:
            matched += 1
        rows.append((str(raw_dep), str(raw_mun) if raw_mun is not None else None,
                     dep_c, mun_c, _distrito_code(raw_dep)))

    map_name = f'geo_map_{table}'
    con.execute(f"DROP TABLE IF EXISTS {map_name}")
    con.execute(f"""
        CREATE TABLE {map_name} (
            raw_dep   VARCHAR,
            raw_mun   VARCHAR,
            dep_codigo INTEGER,
            mun_codigo INTEGER,
            distrito_codigo INTEGER
        )
    """)
    if rows:
        con.executemany(f"INSERT INTO {map_name} VALUES (?, ?, ?, ?, ?)", rows)

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
        dep_c = _dep_code(raw_dep, dep_lk)
        if dep_c:
            matched += 1
        rows.append((str(raw_dep), dep_c, _distrito_code(raw_dep)))

    map_name = f'geo_map_{table}'
    con.execute(f"DROP TABLE IF EXISTS {map_name}")
    con.execute(f"CREATE TABLE {map_name} "
                "(raw_dep VARCHAR, dep_codigo INTEGER, distrito_codigo INTEGER)")
    if rows:
        con.executemany(f"INSERT INTO {map_name} VALUES (?, ?, ?)", rows)

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
                   gm.mun_dane                     AS geo_mun_dane,
                   NULL::INTEGER                   AS geo_distrito_codigo
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
                   NULL::VARCHAR                AS geo_mun_dane,
                   NULL::INTEGER                AS geo_distrito_codigo
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
               mp.dep_codigo      AS geo_dep_codigo,
               mp.mun_codigo      AS geo_mun_codigo,
               gm.dep_dane        AS geo_dep_dane,
               gm.mun_dane        AS geo_mun_dane,
               mp.distrito_codigo AS geo_distrito_codigo
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
               mp.dep_codigo      AS geo_dep_codigo,
               NULL::INTEGER      AS geo_mun_codigo,
               gd.dep_dane        AS geo_dep_dane,
               NULL::VARCHAR      AS geo_mun_dane,
               mp.distrito_codigo AS geo_distrito_codigo
        FROM {table} r
        LEFT JOIN geo_map_{table} mp
               ON r.{dept_col} IS NOT DISTINCT FROM mp.raw_dep
        LEFT JOIN geo_dep gd ON mp.dep_codigo = gd.dep_codigo
    """
    con.execute(sql)


def _create_view_code_first(con, table, code_expr, dept_col, mun_col) -> None:
    """View for sources carrying a municipality code: the code wins when it is a
    valid DIVIPOLA code, otherwise fall back to the name bridge."""
    sql = f"""
        CREATE OR REPLACE VIEW v_{table} AS
        SELECT r.*,
               COALESCE(gp.dep_codigo, mp.dep_codigo) AS geo_dep_codigo,
               COALESCE(gp.mun_codigo, mp.mun_codigo) AS geo_mun_codigo,
               COALESCE(gp.dep_dane,   gm.dep_dane)   AS geo_dep_dane,
               COALESCE(gp.mun_dane,   gm.mun_dane)   AS geo_mun_dane,
               NULL::INTEGER                          AS geo_distrito_codigo
        FROM {table} r
        LEFT JOIN geo_maestro gp
               ON gp.mun_codigo = TRY_CAST({code_expr} AS INTEGER)
        LEFT JOIN geo_map_{table} mp
               ON r.{dept_col} IS NOT DISTINCT FROM mp.raw_dep
              AND r.{mun_col}  IS NOT DISTINCT FROM mp.raw_mun
        LEFT JOIN geo_maestro gm
               ON mp.dep_codigo = gm.dep_codigo
              AND mp.mun_codigo  = gm.mun_codigo
    """
    con.execute(sql)
    total, by_code, mapped = con.execute(f"""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE geo_mun_codigo = TRY_CAST({code_expr} AS INTEGER)),
               COUNT(geo_mun_codigo)
        FROM v_{table} r
    """).fetchone()
    print(f'  v_{table}: {mapped:,}/{total:,} filas con municipio '
          f'({by_code:,} por código, {mapped - by_code:,} por nombre)')


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
        errors: list[str] = []
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
                log.error(f'geo_normalize: error en {table} — {e}')
                errors.append(f'{table}: {e}')

        for table, code_expr, dept_col, mun_col in CODE_FIRST_SOURCES:
            if table not in existing:
                log.info(f'geo_normalize: {table} no existe, saltando.')
                continue
            try:
                _build_map_mun(con, table, dept_col, mun_col, dep_lk, mun_lk)
                _create_view_code_first(con, table, code_expr, dept_col, mun_col)
                n_views += 1
            except Exception as e:
                log.error(f'geo_normalize: error en {table} — {e}')
                errors.append(f'{table}: {e}')

        if errors:
            # Keep building the other views, but don't let a broken one pass silently.
            raise RuntimeError(f'geo_normalize: {len(errors)} vista(s) fallaron — ' + '; '.join(errors))
        print(f'geo_normalize OK — {n_views} vistas creadas')
    finally:
        con.close()


if __name__ == '__main__':
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format='%(levelname)s %(message)s')
    _base = Path(__file__).resolve().parent.parent
    build_all(_base / 'data' / 'informe_regional.duckdb')
