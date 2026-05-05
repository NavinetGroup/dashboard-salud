# -*- coding: utf-8 -*-
"""Cached DuckDB queries and GeoJSON loader for the dashboard."""

import json
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB = Path(__file__).parent.parent / 'data' / 'informe_regional.duckdb'
GEOJSON_PATH = Path(__file__).parent / 'colombia_dptos.geojson'

# ISO 3166-2 -> DANE department code (integer)
ISO_TO_DANE: dict[str, int] = {
    'CO-AMA': 91, 'CO-ANT':  5, 'CO-ARA': 81, 'CO-ATL':  8,
    'CO-BOL': 13, 'CO-BOY': 15, 'CO-CAL': 17, 'CO-CAQ': 18,
    'CO-CAS': 85, 'CO-CAU': 19, 'CO-CES': 20, 'CO-CHO': 27,
    'CO-COR': 23, 'CO-CUN': 25, 'CO-DC':  11, 'CO-GUA': 94,
    'CO-GUV': 95, 'CO-HUI': 41, 'CO-LAG': 44, 'CO-MAG': 47,
    'CO-MET': 50, 'CO-NAR': 52, 'CO-NSA': 54, 'CO-PUT': 86,
    'CO-QUI': 63, 'CO-RIS': 66, 'CO-SAN': 68, 'CO-SAP': 88,
    'CO-SUC': 70, 'CO-TOL': 73, 'CO-VAC': 76, 'CO-VAU': 97,
    'CO-VID': 99,
}

_MES_ORDER = {
    'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4,
    'MAYO': 5, 'JUNIO': 6, 'JULIO': 7, 'AGOSTO': 8,
    'SEPTIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11, 'DICIEMBRE': 12,
}
_PE_ORDER = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
    'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12, 'XIII': 13,
}

_PE_CASE = """CASE periodo_epidemiologico
    WHEN 'I'    THEN 1  WHEN 'II'   THEN 2  WHEN 'III'  THEN 3
    WHEN 'IV'   THEN 4  WHEN 'V'    THEN 5  WHEN 'VI'   THEN 6
    WHEN 'VII'  THEN 7  WHEN 'VIII' THEN 8  WHEN 'IX'   THEN 9
    WHEN 'X'    THEN 10 WHEN 'XI'   THEN 11 WHEN 'XII'  THEN 12
    WHEN 'XIII' THEN 13 ELSE 0 END"""

_MES_CASE = """CASE UPPER(TRIM(mes))
    WHEN 'ENERO'      THEN 1  WHEN 'FEBRERO'   THEN 2
    WHEN 'MARZO'      THEN 3  WHEN 'ABRIL'     THEN 4
    WHEN 'MAYO'       THEN 5  WHEN 'JUNIO'     THEN 6
    WHEN 'JULIO'      THEN 7  WHEN 'AGOSTO'    THEN 8
    WHEN 'SEPTIEMBRE' THEN 9  WHEN 'OCTUBRE'   THEN 10
    WHEN 'NOVIEMBRE'  THEN 11 WHEN 'DICIEMBRE' THEN 12
    ELSE 0 END"""


def _dd(col: str) -> str:
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '.') AS DOUBLE)"


def _di(col: str) -> str:
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '') AS BIGINT)"


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def load_geojson() -> dict:
    with open(GEOJSON_PATH, encoding='utf-8') as f:
        g = json.load(f)
    for feat in g['features']:
        iso = feat['properties'].get('shapeISO', '')
        dane = ISO_TO_DANE.get(iso)
        if dane is not None:
            feat['properties']['DPTO'] = str(dane).zfill(2)
            feat['id'] = str(dane).zfill(2)
    return g


# ---------------------------------------------------------------------------
# Period discovery
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_available_years() -> list[int]:
    """Return sorted-descending list of years present across main sources."""
    con = duckdb.connect(str(DB), read_only=True)
    years: set[int] = set()
    for t in ('afiliacion', 'irca', 'ins_dengue', 'ins_mortalidad_materna'):
        try:
            rs = con.execute(f'SELECT DISTINCT anio FROM {t} WHERE anio IS NOT NULL').fetchall()
            years |= {int(r[0]) for r in rs}
        except Exception:
            pass
    con.close()
    return sorted(years, reverse=True)


@st.cache_data(ttl=3600)
def get_available_months(year: int) -> list[str]:
    """Return months (uppercase Spanish) available in afiliacion for a given year."""
    con = duckdb.connect(str(DB), read_only=True)
    try:
        rs = con.execute(
            "SELECT DISTINCT UPPER(TRIM(mes)) FROM afiliacion WHERE anio = ? AND mes IS NOT NULL",
            [year],
        ).fetchall()
        months = [r[0] for r in rs if r[0] in _MES_ORDER]
        months.sort(key=lambda m: _MES_ORDER.get(m, 99))
    except Exception:
        months = []
    con.close()
    return months


@st.cache_data(ttl=3600)
def get_source_periods() -> dict[str, str]:
    """Return latest available reporting period label for each data source."""
    con = duckdb.connect(str(DB), read_only=True)
    result: dict[str, str] = {}

    def _latest_mes(table: str) -> str:
        try:
            r = con.execute(
                f"SELECT anio, UPPER(TRIM(mes)) FROM {table} "
                f"ORDER BY anio DESC, {_MES_CASE} DESC LIMIT 1"
            ).fetchone()
            return f"{r[1].capitalize()} {r[0]}" if r else 'N/D'
        except Exception:
            return 'N/D'

    def _latest_pe(table: str) -> str:
        try:
            r = con.execute(
                f"SELECT anio, periodo_epidemiologico FROM {table} "
                f"ORDER BY anio DESC, {_PE_CASE} DESC LIMIT 1"
            ).fetchone()
            return f"Período {r[1]}/{r[0]}" if r else 'N/D'
        except Exception:
            return 'N/D'

    result['afiliacion'] = _latest_mes('afiliacion')
    result['aseguramiento'] = result['afiliacion']
    result['irca'] = _latest_mes('irca')
    result['mortalidad_materna'] = _latest_pe('ins_mortalidad_materna')
    result['sifilis_congenita'] = _latest_pe('ins_sifilis_congenita')
    result['desnutricion_aguda'] = _latest_pe('ins_desnutricion_aguda')
    result['mortalidad_menores5'] = _latest_pe('ins_mortalidad_menores5')
    result['dengue'] = _latest_pe('ins_dengue')
    result['intento_suicidio'] = _latest_pe('ins_intento_suicidio')
    result['violencia_genero'] = _latest_pe('ins_violencia_genero')

    try:
        r = con.execute('SELECT MAX(anio) FROM demografico_edad_sexo WHERE anio <= YEAR(CURRENT_DATE)').fetchone()
        result['demografia'] = str(r[0]) if r and r[0] else 'N/D'
    except Exception:
        result['demografia'] = 'N/D'

    try:
        r = con.execute("SELECT MAX(fecha_corte_reps) FROM reps_prestadores").fetchone()
        raw = str(r[0]) if r and r[0] else ''
        result['reps'] = raw.replace('Fecha corte REPS: ', '').strip() if raw else 'N/D'
    except Exception:
        result['reps'] = 'N/D'

    result['dift18'] = 'Evaluacion 2024'
    con.close()
    return result


# ---------------------------------------------------------------------------
# Metrics — base (uses pre-built views = latest data)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_dept_metrics(year: int | None = None, month: str | None = None) -> pd.DataFrame:
    """Return dept-level metrics. When year/month given, overlay time-sensitive columns."""
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT * FROM v_metricas_departamento ORDER BY departamento").df()

    if year is not None:
        df = _overlay_dept_year(con, df, year, month)

    con.close()
    df['dep_str'] = df['geo_dep_codigo'].astype(str).str.zfill(2)
    return df


@st.cache_data(ttl=3600)
def get_mun_metrics(dep_codigo: int | None = None,
                    year: int | None = None,
                    month: str | None = None) -> pd.DataFrame:
    """Return municipality-level metrics, optionally filtered by dept and year/month."""
    con = duckdb.connect(str(DB), read_only=True)
    where = f"WHERE geo_dep_codigo = {dep_codigo}" if dep_codigo is not None else ""
    df = con.execute(f"SELECT * FROM v_metricas_municipio {where} ORDER BY municipio").df()

    if year is not None:
        df = _overlay_mun_year(con, df, year, month, dep_codigo)

    con.close()
    return df


# ---------------------------------------------------------------------------
# Year-filter overlays — replace time-sensitive columns in place
# ---------------------------------------------------------------------------

def _overlay_dept_year(con: duckdb.DuckDBPyConnection,
                       df: pd.DataFrame,
                       year: int,
                       month: str | None) -> pd.DataFrame:
    month_filter = f"AND UPPER(TRIM(mes)) = '{month}'" if month else ""
    pe_filter = ""  # use latest period within year

    patches: list[tuple[str, str]] = [
        # (query_sql, merge_on)
        # Afiliacion
        (f"""
        SELECT geo_dep_codigo,
               SUM(afiliados_subsidiado)                AS afiliados_subsidiado,
               SUM(afiliados_contributivo)              AS afiliados_contributivo,
               SUM(afiliados_total)                     AS afiliados_total,
               AVG(TRY_CAST(Cobertura AS DOUBLE)) * 100 AS cobertura_pct
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_MES_CASE} DESC
            ) AS rn
            FROM v_afiliacion
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {month_filter}
        ) WHERE rn = 1
        GROUP BY geo_dep_codigo
        """, ['afiliados_subsidiado', 'afiliados_contributivo', 'afiliados_total', 'cobertura_pct']),

        # IRCA
        (f"""
        SELECT geo_dep_codigo, AVG(promedio_irca) AS irca_promedio
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_MES_CASE} DESC
            ) AS rn
            FROM v_irca WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {month_filter}
        ) WHERE rn = 1
        GROUP BY geo_dep_codigo
        """, ['irca_promedio']),

        # Mortalidad materna
        (f"""
        SELECT geo_dep_codigo, {_dd('razon_mm_actual')} AS razon_mortalidad_materna
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_dep_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_mortalidad_materna
            WHERE geo_dep_codigo IS NOT NULL AND geo_mun_codigo IS NULL AND anio = {year}
        ) WHERE rn = 1
        """, ['razon_mortalidad_materna']),

        # Sifilis congenita (dept-level: casos_sc_total = NV+MF total per entity)
        (f"""
        SELECT geo_dep_codigo,
               {_di('casos_sc_total')} AS casos_sifilis_congenita,
               NULL::DOUBLE            AS incidencia_sifilis_congenita
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_dep_codigo
                ORDER BY CASE WHEN casos_sc_total IS NOT NULL AND casos_sc_total != '' THEN 0 ELSE 1 END,
                         anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_sifilis_congenita
            WHERE geo_dep_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        """, ['casos_sifilis_congenita', 'incidencia_sifilis_congenita']),

        # Desnutricion aguda
        (f"""
        SELECT geo_dep_codigo,
               AVG({_dd('prevalencia_por_100')}) AS prevalencia_desnutricion_aguda
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_desnutricion_aguda
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        GROUP BY geo_dep_codigo
        """, ['prevalencia_desnutricion_aguda']),

        # Mortalidad menores 5
        (f"""
        SELECT geo_dep_codigo,
               {_dd('tasa_dnt')} AS tasa_mortalidad_menores5_dnt,
               {_dd('tasa_ira')} AS tasa_mortalidad_menores5_ira,
               {_dd('tasa_eda')} AS tasa_mortalidad_menores5_eda
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_dep_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_mortalidad_menores5
            WHERE geo_dep_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        """, ['tasa_mortalidad_menores5_dnt', 'tasa_mortalidad_menores5_ira',
               'tasa_mortalidad_menores5_eda']),

        # Dengue
        (f"""
        SELECT geo_dep_codigo,
               {_dd('dengue_total')} AS dengue_total,
               {_dd('dengue_grave_total')} AS dengue_grave_total,
               {_dd('incidencia_x100k')} AS incidencia_dengue_x100k
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_dep_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_dengue WHERE geo_dep_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        """, ['dengue_total', 'dengue_grave_total', 'incidencia_dengue_x100k']),

        # Intento suicidio
        (f"""
        SELECT geo_dep_codigo, AVG({_dd('tasa')}) AS tasa_intento_suicidio
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_intento_suicidio
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        GROUP BY geo_dep_codigo
        """, ['tasa_intento_suicidio']),

        # Violencia genero
        (f"""
        SELECT geo_dep_codigo,
               {_dd('violencia_fisica')} AS violencia_fisica,
               {_dd('violencia_psicologica')} AS violencia_psicologica,
               {_dd('negligencia_abandono')} AS negligencia_abandono,
               {_dd('violencia_sexual')} AS violencia_sexual,
               {_dd('violencia_genero_intrafamiliar')} AS violencia_genero_intrafamiliar
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_dep_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_violencia_genero WHERE geo_dep_codigo IS NOT NULL AND anio = {year}
        ) WHERE rn = 1
        """, ['violencia_fisica', 'violencia_psicologica', 'negligencia_abandono',
               'violencia_sexual', 'violencia_genero_intrafamiliar']),
    ]

    for sql, cols in patches:
        try:
            patch = con.execute(sql).df()
            if patch.empty:
                continue
            for c in cols:
                df.drop(columns=[c], errors='ignore', inplace=True)
            df = df.merge(patch[['geo_dep_codigo'] + [c for c in cols if c in patch.columns]],
                          on='geo_dep_codigo', how='left')
        except Exception:
            pass

    # Demographics — year filter
    try:
        dem = con.execute(f"""
            SELECT geo_dep_codigo,
                   SUM(CASE WHEN sexo = 'HOMBRES' THEN poblacion ELSE 0 END) AS pob_hombres,
                   SUM(CASE WHEN sexo = 'MUJERES' THEN poblacion ELSE 0 END) AS pob_mujeres,
                   SUM(poblacion) AS pob_total
            FROM v_demografico_edad_sexo
            WHERE anio = {year} AND geo_dep_codigo IS NOT NULL
            GROUP BY geo_dep_codigo
        """).df()
        if not dem.empty:
            df.drop(columns=['pob_hombres', 'pob_mujeres', 'pob_total'], errors='ignore', inplace=True)
            df = df.merge(dem, on='geo_dep_codigo', how='left')
    except Exception:
        pass

    return df


def _overlay_mun_year(con: duckdb.DuckDBPyConnection,
                      df: pd.DataFrame,
                      year: int,
                      month: str | None,
                      dep_codigo: int | None) -> pd.DataFrame:
    dep_filter = f"AND geo_dep_codigo = {dep_codigo}" if dep_codigo is not None else ""
    month_filter = f"AND UPPER(TRIM(mes)) = '{month}'" if month else ""

    patches: list[tuple[str, list[str]]] = [
        (f"""
        SELECT geo_dep_codigo, geo_mun_codigo,
               afiliados_subsidiado, afiliados_contributivo, afiliados_total,
               TRY_CAST(Cobertura AS DOUBLE) * 100 AS cobertura_pct
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_MES_CASE} DESC
            ) AS rn
            FROM v_afiliacion
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {month_filter} {dep_filter}
        ) WHERE rn = 1
        """, ['afiliados_subsidiado', 'afiliados_contributivo', 'afiliados_total', 'cobertura_pct']),

        (f"""
        SELECT geo_dep_codigo, geo_mun_codigo,
               promedio_irca AS irca_promedio, nivel_riesgo AS irca_nivel_riesgo
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_MES_CASE} DESC
            ) AS rn
            FROM v_irca WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {month_filter} {dep_filter}
        ) WHERE rn = 1
        """, ['irca_promedio', 'irca_nivel_riesgo']),

        (f"""
        SELECT geo_dep_codigo, geo_mun_codigo,
               {_dd('razon_mm_actual')} AS razon_mortalidad_materna
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_mortalidad_materna
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {dep_filter}
        ) WHERE rn = 1
        """, ['razon_mortalidad_materna']),

        # Sifilis congenita is dept-level only — incidencia NULL for municipalities

        (f"""
        SELECT geo_dep_codigo, geo_mun_codigo,
               {_dd('prevalencia_por_100')} AS prevalencia_desnutricion_aguda
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_desnutricion_aguda
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {dep_filter}
        ) WHERE rn = 1
        """, ['prevalencia_desnutricion_aguda']),

        (f"""
        SELECT geo_dep_codigo, geo_mun_codigo,
               {_dd('tasa')} AS tasa_intento_suicidio
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY geo_mun_codigo ORDER BY anio DESC, {_PE_CASE} DESC
            ) AS rn
            FROM v_ins_intento_suicidio
            WHERE geo_mun_codigo IS NOT NULL AND anio = {year} {dep_filter}
        ) WHERE rn = 1
        """, ['tasa_intento_suicidio']),
    ]

    for sql, cols in patches:
        try:
            patch = con.execute(sql).df()
            if patch.empty:
                continue
            for c in cols:
                df.drop(columns=[c], errors='ignore', inplace=True)
            df = df.merge(patch[['geo_mun_codigo'] + [c for c in cols if c in patch.columns]],
                          on='geo_mun_codigo', how='left')
        except Exception:
            pass

    return df


# ---------------------------------------------------------------------------
# DIFT18
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_dift18_dept(dep_codigo: int) -> 'pd.Series | None':
    """Return dept-level DIFT18 row, preferring departamento type over distrito."""
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute("""
            SELECT * FROM v_dift18_departamento
            WHERE geo_dep_codigo = ?
            ORDER BY CASE WHEN tipo = 'departamento' THEN 0 ELSE 1 END
            LIMIT 1
        """, [dep_codigo]).df()
    except Exception:
        return None
    con.close()
    return df.iloc[0] if not df.empty else None


# DANE municipality codes for the 6 special district cities.
_DIST_MUN_CODES: set[int] = {8001, 11001, 76109, 76001, 13001, 47001}


@st.cache_data(ttl=3600)
def get_dift18_dist(mun_codigo: int) -> 'pd.Series | None':
    """Return district-level DIFT18 row (38 dept-style indicators) for the 6 special cities.
    Returns None for any other municipality."""
    if mun_codigo not in _DIST_MUN_CODES:
        return None
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute(
            "SELECT * FROM v_dift18_departamento WHERE mun_codigo_ref = ? LIMIT 1",
            [mun_codigo]
        ).df()
    except Exception:
        return None
    con.close()
    return df.iloc[0] if not df.empty else None


@st.cache_data(ttl=3600)
def get_dift18_mun(mun_codigo: int) -> 'pd.Series | None':
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute(
            "SELECT * FROM v_dift18_municipio WHERE geo_mun_codigo = ?", [mun_codigo]
        ).df()
    except Exception:
        return None
    con.close()
    return df.iloc[0] if not df.empty else None
