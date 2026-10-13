# -*- coding: utf-8 -*-
"""Cached DuckDB queries and GeoJSON loader for the dashboard."""

import json
import os
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# INFORME_DB_PATH env var lets corporate deployments keep the duckdb
# outside the app folder so it survives code upgrades.
DB = Path(os.environ.get('INFORME_DB_PATH',
          str(Path(__file__).parent.parent / 'data' / 'informe_regional.duckdb')))
DB_URL = 'https://github.com/NavinetGroup/dashboard-salud/releases/download/data-v1/informe_regional.duckdb'
GEOJSON_PATH = Path(__file__).parent / 'colombia_dptos.geojson'


@st.cache_resource(show_spinner=False)
def _ensure_db() -> str:
    if not DB.exists():
        DB.parent.mkdir(parents=True, exist_ok=True)
        with st.spinner('Descargando base de datos (~208 MB, solo primera carga)...'):
            urllib.request.urlretrieve(DB_URL, DB)
    return str(DB)


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(_ensure_db(), read_only=True)

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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
# Metrics — computed by the pipeline (pipeline/metricas.py)
#
# metricas_*_periodo hold one row per entity for every (year, month) offered by
# the selectors; the v_metricas_* views hold the latest data. The dashboard only
# filters rows: no metric is re-derived here, so the numbers always match the
# pipeline's period rules and weighted aggregations.
# ---------------------------------------------------------------------------

def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def _metrics(level: str, year: int | None, month: str | None,
             dep_codigo: int | None = None) -> pd.DataFrame:
    con = _connect()
    try:
        params: list = []
        dep_sql = ''
        if dep_codigo is not None:
            dep_sql = 'AND geo_dep_codigo = ?'
            params.append(int(dep_codigo))
        order = 'municipio' if level == 'municipio' else 'departamento'
        table = f'metricas_{level}_periodo'
        if year is not None and _has_table(con, table):
            df = con.execute(
                f"SELECT * EXCLUDE (anio_filtro, mes_filtro) FROM {table} "
                f"WHERE anio_filtro = ? AND mes_filtro IS NOT DISTINCT FROM ? {dep_sql} "
                f"ORDER BY {order}",
                [int(year), month, *params],
            ).df()
            if not df.empty:
                return df
        # Latest data (also the fallback for a DB built before the period tables existed)
        return con.execute(
            f"SELECT * FROM v_metricas_{level} WHERE TRUE {dep_sql} ORDER BY {order}", params
        ).df()
    finally:
        con.close()


@st.cache_data(ttl=3600)
def get_dept_metrics(year: int | None = None, month: str | None = None) -> pd.DataFrame:
    """Dept-level metrics for the selected year/month (None = latest data)."""
    df = _metrics('departamento', year, month)
    df['dep_str'] = df['geo_dep_codigo'].astype(str).str.zfill(2)
    return df


@st.cache_data(ttl=3600)
def get_nat_metrics(year: int | None = None, month: str | None = None) -> pd.Series:
    """National reference row (true national rates). Empty on a DB built before it existed."""
    con = _connect()
    try:
        if year is not None and _has_table(con, 'metricas_nacional_periodo'):
            df = con.execute(
                "SELECT * EXCLUDE (anio_filtro, mes_filtro) FROM metricas_nacional_periodo "
                "WHERE anio_filtro = ? AND mes_filtro IS NOT DISTINCT FROM ?",
                [int(year), month]).df()
            if not df.empty:
                return df.iloc[0]
        if _has_table(con, 'v_metricas_nacional'):
            df = con.execute("SELECT * FROM v_metricas_nacional").df()
            if not df.empty:
                return df.iloc[0]
        return pd.Series(dtype=object)
    finally:
        con.close()


@st.cache_data(ttl=3600)
def get_mun_metrics(dep_codigo: int | None = None,
                    year: int | None = None,
                    month: str | None = None) -> pd.DataFrame:
    """Municipality-level metrics, optionally filtered by dept, for the selected period."""
    return _metrics('municipio', year, month, dep_codigo)


# ---------------------------------------------------------------------------
# DIFT18
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_dift18_dept(dep_codigo: int) -> 'pd.Series | None':
    """Return dept-level DIFT18 row, preferring departamento type over distrito."""
    con = _connect()
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
    con = _connect()
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
    con = _connect()
    try:
        df = con.execute(
            "SELECT * FROM v_dift18_municipio WHERE geo_mun_codigo = ?", [mun_codigo]
        ).df()
    except Exception:
        return None
    con.close()
    return df.iloc[0] if not df.empty else None
