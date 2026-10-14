# -*- coding: utf-8 -*-
"""Cached DuckDB queries and GeoJSON loader for the dashboard."""

import hashlib
import json
import os
import shutil
import tomllib
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# ── Where the data comes from ────────────────────────────────────────────────
# 1. INFORME_DB_PATH: an explicit file, used as is (never updated).
# 2. The processing machine: the pipeline's own database in data/ — the
#    operator always sees the build they just made.
# 3. The viewer (everyone else): data/informe_regional_visor.duckdb, kept up to
#    date on start-up by
#      A  a newer viewer database in data/actualizacion/ (copied by hand from a
#         USB stick, an email…) or in the shared folder set in the configuration
#         (a SharePoint library synced with OneDrive, a network drive) is
#         installed: copied, verified and swapped in atomically;
#      B  the manifest at the configured URL (a GitHub release by default) says
#         which version is published; a newer one is downloaded, its SHA-256
#         checked, and swapped in the same way.
#    Without internet or without the shared folder the current copy keeps working.
#
# Configuration: informe_regional.toml next to the app (app/ in the portable
# bundle, the repository root otherwise), section [tablero]; environment
# variables win over the file.
#   url_actualizacion      INFORME_RELEASE_URL   base URL with manifest.json ('' = off)
#   carpeta_actualizacion  INFORME_UPDATE_DIR    shared folder with the monthly file
_APP_ROOT = Path(__file__).parent.parent
_DATA_DIR = Path(os.environ.get('INFORME_DATA_DIR', str(_APP_ROOT / 'data')))
_PIPELINE_DB = _APP_ROOT / 'data' / 'informe_regional.duckdb'
VIEWER_DB = _DATA_DIR / 'informe_regional_visor.duckdb'
DROP_DIR = _DATA_DIR / 'actualizacion'


def _config() -> dict:
    try:
        return tomllib.loads((_APP_ROOT / 'informe_regional.toml').read_text(encoding='utf-8')).get('tablero', {})
    except FileNotFoundError:
        return {}
    except Exception as e:   # a typo in the file must not take the app down
        return {'_error': str(e)}


def _setting(env: str, key: str, default: str) -> str:
    value = os.environ.get(env)
    return value if value is not None else str(_config().get(key, default))


GITHUB_REPO = os.environ.get('INFORME_GITHUB_REPO', 'NavinetGroup/dashboard-salud')
RELEASE_URL = _setting('INFORME_RELEASE_URL', 'url_actualizacion',
                       f'https://github.com/{GITHUB_REPO}/releases/latest/download').rstrip('/')
_shared = _setting('INFORME_UPDATE_DIR', 'carpeta_actualizacion', '')
SHARED_DIR = Path(os.path.expandvars(os.path.expanduser(_shared))) if _shared else None
# DANE Marco Geoestadístico Nacional, simplified (tools/build_geojson.py)
GEOJSON_PATH = Path(__file__).parent / 'colombia_dptos.geojson'
GEOJSON_MPIOS_PATH = Path(__file__).parent / 'colombia_mpios.geojson'


def _db_version(path: Path) -> str:
    """Version stamp of a viewer database ('' if missing or not one)."""
    try:
        con = duckdb.connect(str(path), read_only=True)
        try:
            row = con.execute("SELECT valor FROM _visor_info WHERE clave = 'version'").fetchone()
            ok = con.execute("SELECT COUNT(*) FROM duckdb_tables() "
                             "WHERE table_name = 'metricas_nacional_periodo'").fetchone()[0]
            return row[0] if row and ok else ''
        finally:
            con.close()
    except Exception:
        return ''


def _install(candidate: Path) -> bool:
    """Swap a verified newer viewer database into place (atomic rename)."""
    new, cur = _db_version(candidate), _db_version(VIEWER_DB) if VIEWER_DB.exists() else ''
    if not new or new <= cur:
        return False
    os.replace(candidate, VIEWER_DB)
    return True


def _from_folder(folder: Path, consume: bool) -> str:
    """A: newest valid viewer database in a folder ('' if none newer than ours).
    consume=True (data/actualizacion/, the user's own drop folder): a file that is
    a viewer database is deleted once looked at, newer or not, so it is not
    re-checked on every start. consume=False (the shared folder, used by every
    tableau): files are only read. Anything that is not a viewer database is
    left alone."""
    if not folder.is_dir():
        return ''
    staged = VIEWER_DB.with_name(VIEWER_DB.name + '.part')
    current = _db_version(VIEWER_DB)
    for f in sorted(folder.glob('*.duckdb'), key=_db_version, reverse=True):
        version = _db_version(f)
        if not version:
            continue
        installed = False
        if version > current:
            try:
                staged.unlink(missing_ok=True)
                shutil.copyfile(f, staged)
                installed = _install(staged)
            finally:
                staged.unlink(missing_ok=True)
        if consume:
            f.unlink(missing_ok=True)
        if installed:
            return version
    return ''


def _from_release() -> str:
    """B: download the latest published version if it is newer ('' if not)."""
    with urllib.request.urlopen(f'{RELEASE_URL}/manifest.json', timeout=8) as resp:
        manifest = json.loads(resp.read().decode('utf-8'))
    current = _db_version(VIEWER_DB) if VIEWER_DB.exists() else ''
    if manifest.get('version', '') <= current:
        return ''
    part = VIEWER_DB.with_name(VIEWER_DB.name + '.part')
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(f"{RELEASE_URL}/{manifest['archivo']}", timeout=60) as resp,                 open(part, 'wb') as out:
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != manifest.get('sha256', '').lower():
            raise RuntimeError('la descarga no coincide con el SHA-256 publicado')
        return manifest['version'] if _install(part) else ''
    finally:
        part.unlink(missing_ok=True)


# What the last update check did, for app.py to report (a cached function must
# not draw Streamlit elements itself: they would be replayed on every cache hit).
_STATUS = {'updated': '', 'problems': ''}


@st.cache_resource(show_spinner='Buscando una versión más reciente de los datos…', ttl=6 * 3600)
def _ensure_db() -> str:
    """Path of the database to read, updating the viewer copy first (see above);
    '' when there is no usable viewer database. Cached for 6 h, so a long-running
    app also picks up the monthly release."""
    explicit = os.environ.get('INFORME_DB_PATH')
    if explicit:
        return explicit
    if _PIPELINE_DB.exists():
        return str(_PIPELINE_DB)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    DROP_DIR.mkdir(exist_ok=True)
    updated, problems = '', []
    if '_error' in _config():
        problems.append(f"informe_regional.toml: {_config()['_error']}")
    # No source may take the app down: offline, the URL unreachable, the shared
    # folder not synced, a bad or half-copied file, or the current database
    # locked by another window all leave the current copy in place and are
    # reported in the sidebar.
    try:
        updated = _from_folder(DROP_DIR, consume=True)
    except Exception as e:
        problems.append(f'carpeta de actualización: {e}')
    if SHARED_DIR is not None:
        try:
            updated = _from_folder(SHARED_DIR, consume=False) or updated
        except Exception as e:
            problems.append(f'carpeta compartida: {e}')
    if RELEASE_URL:
        try:
            updated = _from_release() or updated
        except Exception as e:
            problems.append(f'descarga: {e}')
    _STATUS.update(updated=updated, problems='; '.join(problems))
    if updated:
        st.cache_data.clear()
    return str(VIEWER_DB) if _db_version(VIEWER_DB) else ''


def _db_path() -> str:
    """The database to read; stops the page with instructions when there is none."""
    path = _ensure_db()
    if path:
        return path
    st.error('El archivo de datos está dañado o incompleto.' if VIEWER_DB.exists()
             else 'No hay datos para mostrar todavía.')
    st.markdown(
        '- **Automático:** conecte el equipo a internet y recargue la página; la aplicación '
        'descargará la última versión publicada.\n'
        '- **Manual:** copie el archivo `informe_regional_visor.duckdb` que le compartieron en '
        f'la carpeta `{DROP_DIR}` y recargue.')
    if _STATUS['problems']:
        st.caption('Detalle: ' + _STATUS['problems'])
    st.stop()
    return ''


def data_version() -> str:
    """Version stamp shown in the sidebar ('' for the pipeline's own database)."""
    return _db_version(Path(_db_path()))


def update_status() -> dict:
    """{'updated': version just installed or '', 'problems': why no check was possible or ''}."""
    _db_path()
    return _STATUS


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(_db_path(), read_only=True)

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
    """Departments; feature id and properties.DPTO = 2-digit DANE code."""
    with open(GEOJSON_PATH, encoding='utf-8') as f:
        return json.load(f)


@st.cache_data(ttl=3600)
def _mpios_all() -> list[dict]:
    with open(GEOJSON_MPIOS_PATH, encoding='utf-8') as f:
        feats = json.load(f)['features']
    for x in feats:   # bounding box, for the neighbours map
        xs, ys = [], []

        def walk(c):
            if c and isinstance(c[0], (int, float)):
                xs.append(c[0]); ys.append(c[1])
            else:
                for y in c:
                    walk(y)
        walk(x['geometry']['coordinates'])
        x['bbox'] = [min(xs), min(ys), max(xs), max(ys)]
    return feats


def load_geojson_mpios(dep_code: int) -> dict:
    """One department's municipalities; feature id and properties.MPIO = 5-digit
    DIVIPOLA code (Bogotá: its single polygon)."""
    dep = str(int(dep_code)).zfill(2)
    return {'type': 'FeatureCollection',
            'features': [x for x in _mpios_all() if x['properties']['DPTO'] == dep]}


def load_geojson_vecinos(mun_code: int, margin: float = 0.02) -> dict:
    """The municipality and those around it, across department lines: every
    municipality whose bounding box overlaps its own (slightly enlarged). A
    superset of strict adjacency, labelled 'y alrededores'."""
    feats = _mpios_all()
    me = next((x for x in feats if x['id'] == str(int(mun_code)).zfill(5)), None)
    if me is None:
        return {'type': 'FeatureCollection', 'features': []}
    x0, y0, x1, y1 = me['bbox']
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    return {'type': 'FeatureCollection', 'features': [
        x for x in feats
        if x['bbox'][0] <= x1 and x['bbox'][2] >= x0 and x['bbox'][1] <= y1 and x['bbox'][3] >= y0]}


# ---------------------------------------------------------------------------
# Period discovery
# ---------------------------------------------------------------------------

# The selectors offer exactly the (year, month) grid the pipeline computed:
# metricas_nacional_periodo holds one row per period (mes_filtro NULL = latest
# in the year). Reading it, not the raw source tables, lets the viewer run on
# the slim database (pipeline/exportar.py), which has no raw tables.

@st.cache_data(ttl=3600)
def get_available_years() -> list[int]:
    """Years offered by the selector, newest first."""
    con = _connect()
    try:
        if not _has_table(con, 'metricas_nacional_periodo'):
            return []
        rs = con.execute('SELECT DISTINCT anio_filtro FROM metricas_nacional_periodo').fetchall()
        return sorted((int(r[0]) for r in rs if r[0] is not None), reverse=True)
    finally:
        con.close()


@st.cache_data(ttl=3600)
def get_available_months(year: int) -> list[str]:
    """Months (Spanish, upper case) offered for a year, in calendar order."""
    con = _connect()
    try:
        if not _has_table(con, 'metricas_nacional_periodo'):
            return []
        rs = con.execute('SELECT DISTINCT mes_filtro FROM metricas_nacional_periodo '
                         'WHERE anio_filtro = ? AND mes_filtro IS NOT NULL', [int(year)]).fetchall()
        return sorted((r[0] for r in rs if r[0] in _MES_ORDER), key=lambda m: _MES_ORDER[m])
    finally:
        con.close()


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
        # Latest data: the full pipeline DB has the v_metricas_* views; the slim
        # viewer DB only has the period tables (latest year, mes_filtro NULL).
        if _has_table(con, f'v_metricas_{level}'):
            return con.execute(
                f"SELECT * FROM v_metricas_{level} WHERE TRUE {dep_sql} ORDER BY {order}", params
            ).df()
        return con.execute(
            f"SELECT * EXCLUDE (anio_filtro, mes_filtro) FROM {table} "
            f"WHERE anio_filtro = (SELECT MAX(anio_filtro) FROM {table}) AND mes_filtro IS NULL "
            f"{dep_sql} ORDER BY {order}", params).df()
    finally:
        con.close()


@st.cache_data(ttl=3600)
def get_dept_metrics(year: int | None = None, month: str | None = None) -> pd.DataFrame:
    """Dept-level metrics for the selected year/month (None = latest data)."""
    df = _metrics('departamento', year, month)
    df['dep_str'] = df['geo_dep_codigo'].astype(str).str.zfill(2)
    return df


@st.cache_data(ttl=3600)
def get_prev_metrics(level: str, year: int | None, month: str | None,
                     code: int | None = None) -> pd.Series:
    """The same metrics for the same period one year earlier (metricas_*_anterior),
    for the trend arrows. level: 'municipio' | 'departamento' | 'nacional'."""
    if year is None:
        return pd.Series(dtype=object)
    con = _connect()
    try:
        table = f'metricas_{level}_anterior'
        if not _has_table(con, table):
            return pd.Series(dtype=object)
        key = {'municipio': 'geo_mun_codigo', 'departamento': 'geo_dep_codigo'}.get(level)
        where, params = 'anio_filtro = ? AND mes_filtro IS NOT DISTINCT FROM ?', [int(year), month]
        if key and code is not None:
            where += f' AND {key} = ?'
            params.append(int(code))
        df = con.execute(f"SELECT * EXCLUDE (anio_filtro, mes_filtro) FROM {table} WHERE {where}",
                         params).df()
        return df.iloc[0] if len(df) == 1 else pd.Series(dtype=object)
    finally:
        con.close()


@st.cache_data(ttl=3600)
def get_monthly_series(level: str, cols: tuple[str, ...], code: int | None = None) -> pd.DataFrame:
    """Monthly values (one row per afiliación month) for sparklines."""
    con = _connect()
    try:
        table = f'metricas_{level}_periodo'
        if not _has_table(con, table):
            return pd.DataFrame()
        key = {'municipio': 'geo_mun_codigo', 'departamento': 'geo_dep_codigo'}.get(level)
        where, params = 'mes_filtro IS NOT NULL', []
        if key and code is not None:
            where += f' AND {key} = ?'
            params.append(int(code))
        df = con.execute(
            f"SELECT anio_filtro AS anio, mes_filtro AS mes, {', '.join(cols)} FROM {table} WHERE {where}",
            params).df()
    finally:
        con.close()
    df['orden'] = df['anio'] * 100 + df['mes'].map(_MES_ORDER)
    return df.sort_values('orden').reset_index(drop=True)


@st.cache_data(ttl=3600)
def get_piramide(level: str, code: int | None) -> pd.DataFrame:
    """Affiliates by regime × sex × age group (BDUA, current snapshot)."""
    con = _connect()
    try:
        if not _has_table(con, 'piramide_afiliados'):
            return pd.DataFrame()
        return con.execute(
            "SELECT regimen, sexo, grupo_edad, orden_edad, afiliados, fecha_corte "
            "FROM piramide_afiliados WHERE nivel = ? AND codigo = ? ORDER BY orden_edad",
            [level, 0 if level == 'nacional' else int(code)]).df()
    finally:
        con.close()


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



