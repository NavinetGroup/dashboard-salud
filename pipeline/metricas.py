# -*- coding: utf-8 -*-
"""
metricas.py — Vistas consolidadas de métricas de salud por municipio y departamento.

Crea:
  v_metricas_municipio    — una fila por municipio DANE con ~35 indicadores
  v_metricas_departamento — una fila por departamento con los mismos indicadores
                            (fuentes dept-only incluidas; fuentes municipio se agregan)

Requiere que geo_normalize.build_all() ya haya creado las vistas v_* y geo_maestro/geo_dep.

Reglas de periodo y agregación:
  - Población y pertenencia étnica usan el mismo año de proyección DANE (el último ≤ año actual).
  - Afiliación y tablas INS: un único periodo, el más reciente de cada fuente (no "el último de
    cada municipio", que mezclaba boletines de distintos años). Cada fuente expone su periodo
    en una columna periodo_* para que el dashboard lo rotule.
  - IRCA: los municipios muestrean en meses distintos, así que se toma la medición más reciente
    de cada municipio dentro de los 12 meses previos al último mes disponible (irca_periodo).
  - Departamento: tasas ponderadas (Σnumerador / Σdenominador), nunca promedio simple de tasas.
  - INS publica los distritos (Barranquilla, Cartagena, Santa Marta, Cali, Buenaventura) como
    entidades aparte: la fila del departamento NO los incluye. Esas filas de distrito alimentan
    al municipio correspondiente en v_metricas_municipio.

Run: python pipeline/metricas.py
"""

import logging
from pathlib import Path

import duckdb

try:
    from scrapers.geo_normalize import DISTRICTS
except ImportError:  # run directly as `python pipeline/metricas.py`
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.geo_normalize import DISTRICTS

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / 'data' / 'informe_regional.duckdb'

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

# Sortable period keys (YYYYPP / YYYYMM) and display labels
_PE_KEY = f"(anio * 100 + ({_PE_CASE}))"
_MES_KEY = f"(anio * 100 + ({_MES_CASE}))"
_PE_LABEL = "(CAST(anio AS VARCHAR) || ' PE ' || periodo_epidemiologico)"
_MES_LABEL = "(UPPER(TRIM(mes)) || ' ' || CAST(anio AS VARCHAR))"

_MESES = ('ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO',
          'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE')


def _pob_year(year: int | None) -> str:
    """One DANE projection year for every population figure (latest ≤ the scope year)."""
    ceiling = int(year) if year is not None else 'YEAR(CURRENT_DATE)'
    return f"(SELECT MAX(anio) FROM demografico_edad_sexo WHERE anio <= {ceiling})"


def _year_cond(year: int | None) -> str:
    return f"anio = {int(year)}" if year is not None else "TRUE"


def _month_cond(month: str | None) -> str:
    if month is None:
        return "TRUE"
    if month not in _MESES:
        raise ValueError(f'mes inválido: {month!r}')
    return f"UPPER(TRIM(mes)) = '{month}'"

# INS entity rows: a department's own row (districts are separate entities)
# entidad_territorial IS NOT NULL: municipal rows whose municipality did not
# match (PDF residue) also have no geo_mun_codigo and must not pass for the
# department's own row (Antioquia MM read 591.7 instead of 32.6 at 2026 PE IX).
_DEPT_ROW = ("geo_dep_codigo IS NOT NULL AND geo_mun_codigo IS NULL AND geo_distrito_codigo IS NULL "
             "AND entidad_territorial IS NOT NULL")
_DISTRICT_ROW = "geo_distrito_codigo IS NOT NULL"
_COUNTRY_ROW = "TRIM(entidad_territorial) ILIKE 'colombia'"

# REPS installed capacity by type (grupo_capacidad / coca_nombre). Neonatal
# intensive beds are not counted as paediatric ICU. 0 (not NULL) when the
# territory reports capacity but none of that type (e.g. no ICU in Amazonas).
_CAP_COLS = ('camas', 'consultorios', 'salas_cirugia', 'uci_adultos', 'uci_pediatricas')
_CAP_TYPES = """COALESCE(SUM(TRY_CAST(cantidad AS DOUBLE)) FILTER (WHERE grupo_capacidad = 'CAMAS'), 0) AS camas,
           COALESCE(SUM(TRY_CAST(cantidad AS DOUBLE)) FILTER (WHERE grupo_capacidad = 'CONSULTORIOS'), 0) AS consultorios,
           COALESCE(SUM(TRY_CAST(cantidad AS DOUBLE)) FILTER (
               WHERE TRIM(coca_nombre) IN ('Sala de Cirugía', 'Quirófano')), 0) AS salas_cirugia,
           COALESCE(SUM(TRY_CAST(cantidad AS DOUBLE)) FILTER (
               WHERE TRIM(coca_nombre) IN ('Intensiva Adultos', 'Cuidado Intensivo Adulto',
                                           'Intensiva Quemado Adulto')), 0) AS uci_adultos,
           COALESCE(SUM(TRY_CAST(cantidad AS DOUBLE)) FILTER (
               WHERE TRIM(coca_nombre) IN ('Intensiva Pediátrica', 'Cuidado Intensivo Pediátrico',
                                           'Intensiva Quemado pediátrica', 'Cuna Intensiva Pediátrica')), 0)
               AS uci_pediatricas"""

# BDUA: an EPS appears under one code per regime plus "-CM" mobility codes
# (e.g. EPSS41 NUEVA EPS S.A. and EPSS37 NUEVA EPS S.A. -CM). The entity is the
# name without the -CM suffix; an EPS counts for a regime only with that
# regime's own code. BDUA lists EPS *with affiliates* in each territory (the
# authorisation by territory is not published). The key ignores punctuation
# (the same EPS appears with and without a closing quote). Entidades Adaptadas
# (codes EAS*, e.g. Fondo Pasivo Ferrocarriles) are not EPS and are excluded.
_EPS_KEY = ("TRIM(REGEXP_REPLACE(REGEXP_REPLACE(UPPER(STRIP_ACCENTS(ent_nombre)), "
            "'\\s*-\\s*CM\\s*$', ''), '[^A-Z0-9]+', ' ', 'g'))")
_EPS_CM = "REGEXP_MATCHES(UPPER(ent_nombre), '-\\s*CM\\s*$')"


def _eps_counts(group_cols: str, where: str) -> str:
    return f"""
    SELECT {group_cols}{', ' if group_cols else ''}
           COUNT(DISTINCT k) AS eps_total,
           COUNT(DISTINCT k) FILTER (WHERE regimen = 'contributivo' AND NOT cm) AS eps_contributivo,
           COUNT(DISTINCT k) FILTER (WHERE regimen = 'subsidiado' AND NOT cm) AS eps_subsidiado,
           CAST(MAX(fecha_corte) AS VARCHAR) AS eps_fecha_corte
    FROM (SELECT *, {_EPS_KEY} AS k, {_EPS_CM} AS cm FROM v_bdua_eps
          WHERE afiliados > 0 AND ent_id NOT LIKE 'EAS%' AND {where})
    {('GROUP BY ' + group_cols) if group_cols else ''}"""


_EPS_COLS = ('eps_total', 'eps_contributivo', 'eps_subsidiado', 'eps_fecha_corte')

# Afiliación: subsidised-regime affiliates without Sisbén IV classification (FCT Aseguramiento 8–11)
_SISBEN_SRC = {
    'afil_sin_sisben':             '"Afil. Subsidiado sin SISBEN IV"',
    'afil_especiales_sin_sisben':  '"Afil. Pob. Especiales Subsidiado sin SISBEN IV"',
    'afil_oficio_sin_sisben':      '"Afil. de Oficio sin SISBEN IV"',
    'afil_no_pobre_no_vulnerable': '"Afil. Régimen Sub. No Pobre, No Vulnerable"',
}
_SISBEN_COLS = tuple(_SISBEN_SRC)
_SISBEN_MUN = ',\n           '.join(f'TRY_CAST({src} AS BIGINT) AS {col}' for col, src in _SISBEN_SRC.items())
_SISBEN_SUM = ',\n           '.join(f'SUM(TRY_CAST({src} AS BIGINT)) AS {col}' for col, src in _SISBEN_SRC.items())
_DISTRICT_CODES = ', '.join(str(c) for c in sorted(set(DISTRICTS.values())))

# _DENGUE_GRAVE_NOTE: the INS PDF dengue table's columns shift between bulletins.
# The column extracted as dengue_grave_total is another category (2025 PE IX:
# 36,896 vs 989 severe cases in the SIVIGILA microdata), so severe dengue is not
# published from the PDF. It returns with the SIVIGILA rebuild.

# Dengue incidence is computed here (cases / DANE population · 100k) instead of read
# from the INS PDF: the 2026 bulletins lost their decimal comma ('471,8' → '4718'),
# so the extracted rate is off by an unknown power of ten. INS divides by population
# at risk, so this total-population rate is lower than the bulletin's; the dashboard
# labels it. The SIVIGILA rebuild will use this same method.


def _dd(col: str) -> str:
    """TRY_CAST a PDF-extracted column to DOUBLE, handling Spanish decimal comma.

    Removes thousands-separator dots first, then converts decimal commas to dots.
    E.g. '2.069,0' → '2069.0' → 2069.0
    """
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '.') AS DOUBLE)"


def _di(col: str) -> str:
    """TRY_CAST a PDF-extracted column to BIGINT, stripping dots and commas."""
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '') AS BIGINT)"


def _latest(view: str, where: str, key: str, entity: str, order: str) -> str:
    """Rows of `view` at its single most recent period, one row per `entity`.

    The period is global to the source (MAX over all rows matching `where`), so a
    municipality missing from the newest report gets no row instead of an old value.
    `order` breaks ties deterministically when a report lists an entity twice.
    """
    return f"""
    SELECT * FROM {view}
    WHERE {where}
      AND {key} = (SELECT MAX({key}) FROM {view} WHERE {where})
    QUALIFY ROW_NUMBER() OVER (PARTITION BY {entity} ORDER BY {order}) = 1"""


def _pe_cap(view: str, caps: dict | None) -> str:
    """Limit an INS view to periods ≤ the cap (used for the same period a year earlier)."""
    n = (caps or {}).get('pe', {}).get(view)
    return f"({_PE_CASE}) <= {int(n)}" if n else "TRUE"


def _irca_latest_per_mun(year: int | None = None, month: str | None = None,
                         caps: dict | None = None) -> str:
    """Each municipality's most recent IRCA within 12 months of the newest month in scope."""
    m = (caps or {}).get('irca_mes') or (_MESES.index(month) + 1 if month else None)
    scope = f"{_year_cond(year)} AND {_MES_KEY} <= {int(year) * 100 + int(m)}" \
        if year is not None and m else _year_cond(year)
    ceiling = f"(SELECT MAX({_MES_KEY}) FROM v_irca WHERE {scope})"
    return f"""
    SELECT * FROM v_irca
    WHERE geo_mun_codigo IS NOT NULL
      AND {_MES_KEY} <= {ceiling}
      AND {_MES_KEY} > {ceiling} - 100
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY geo_mun_codigo ORDER BY {_MES_KEY} DESC, n_muestras DESC NULLS LAST) = 1"""


def _afil_latest(year: int | None = None, month: str | None = None,
                 caps: dict | None = None) -> str:
    month = (caps or {}).get('afil_mes') or month
    where = f"geo_mun_codigo IS NOT NULL AND {_year_cond(year)} AND {_month_cond(month)}"
    return _latest('v_afiliacion', where, _MES_KEY,
                   'geo_mun_codigo', 'afiliados_total DESC NULLS LAST')


# ---------------------------------------------------------------------------
# Municipio view
# ---------------------------------------------------------------------------

def _municipio_sql(ev: dict[str, bool], year: int | None = None, month: str | None = None,
                   caps: dict | None = None) -> str:
    """SELECT for one row per municipio. year/month narrow the time-varying sources
    (afiliación, IRCA, INS); None means the latest data available."""
    pob_year = _pob_year(year)

    def ins(view, where, entity, order):
        return _latest(view, f"({where}) AND {_year_cond(year)} AND {_pe_cap(view, caps)}",
                       _PE_KEY, entity, order)

    ctefile: list[tuple[str, str]] = []
    join_clauses: list[str] = []
    select_extra: list[str] = []

    # ── Demografía ───────────────────────────────────────────────────────────
    if ev.get('v_demografico_edad_sexo'):
        ctefile.append(('dem', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           SUM(CASE WHEN sexo = 'HOMBRES' THEN poblacion ELSE 0 END) AS pob_hombres,
           SUM(CASE WHEN sexo = 'MUJERES' THEN poblacion ELSE 0 END) AS pob_mujeres,
           SUM(poblacion) AS pob_total
    FROM v_demografico_edad_sexo
    WHERE anio = {pob_year}
      AND geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN dem   ON gm.dep_codigo = dem.geo_dep_codigo AND gm.mun_codigo = dem.geo_mun_codigo")
        select_extra += ['dem.pob_hombres', 'dem.pob_mujeres', 'dem.pob_total']
    else:
        select_extra += ['NULL::BIGINT AS pob_hombres', 'NULL::BIGINT AS pob_mujeres', 'NULL::BIGINT AS pob_total']

    # ── Étnico-racial (same projection year as pob_total) ────────────────────
    if ev.get('v_demografico_etnico'):
        ctefile.append(('etnico', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           SUM(poblacion) AS pob_etnico_total,
           SUM(CASE WHEN grupo_etnico ILIKE '%ndígen%' OR grupo_etnico ILIKE '%ndigen%'
                    THEN poblacion ELSE 0 END) AS pob_indigena,
           SUM(CASE WHEN grupo_etnico ILIKE '%itana%' OR grupo_etnico ILIKE '%rrom%'
                    THEN poblacion ELSE 0 END) AS pob_gitana_rrom,
           SUM(CASE WHEN grupo_etnico ILIKE '%aizal%'
                    THEN poblacion ELSE 0 END) AS pob_raizal,
           SUM(CASE WHEN grupo_etnico ILIKE '%alenquer%'
                    THEN poblacion ELSE 0 END) AS pob_palenquera,
           SUM(CASE WHEN grupo_etnico ILIKE '%egra%' OR grupo_etnico ILIKE '%fro%'
                    THEN poblacion ELSE 0 END) AS pob_negra_afro,
           SUM(CASE WHEN grupo_etnico ILIKE '%ingún%' OR grupo_etnico ILIKE '%ningun%'
                    THEN poblacion ELSE 0 END) AS pob_ninguno
    FROM v_demografico_etnico
    WHERE anio = {pob_year}
      AND geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN etnico ON gm.dep_codigo = etnico.geo_dep_codigo AND gm.mun_codigo = etnico.geo_mun_codigo")
        select_extra += [
            'etnico.pob_etnico_total', 'etnico.pob_indigena', 'etnico.pob_gitana_rrom',
            'etnico.pob_raizal', 'etnico.pob_palenquera', 'etnico.pob_negra_afro', 'etnico.pob_ninguno',
            'etnico.pob_etnico_total - etnico.pob_ninguno AS pob_con_pertenencia',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS pob_etnico_total', 'NULL::BIGINT AS pob_indigena',
            'NULL::BIGINT AS pob_gitana_rrom', 'NULL::BIGINT AS pob_raizal',
            'NULL::BIGINT AS pob_palenquera', 'NULL::BIGINT AS pob_negra_afro',
            'NULL::BIGINT AS pob_ninguno', 'NULL::BIGINT AS pob_con_pertenencia',
        ]

    # ── IPS habilitadas ──────────────────────────────────────────────────────
    if ev.get('v_reps_prestadores'):
        ctefile.append(('ips', """
    SELECT geo_dep_codigo, geo_mun_codigo,
           COUNT(*) AS ips_total,
           COUNT(CASE WHEN naju_nombre ILIKE '%ública%' THEN 1 END) AS ips_publica,
           COUNT(CASE WHEN naju_nombre ILIKE '%rivada%' THEN 1 END) AS ips_privada,
           COUNT(CASE WHEN naju_nombre ILIKE '%ixta%'   THEN 1 END) AS ips_mixta
    FROM v_reps_prestadores
    WHERE geo_mun_codigo IS NOT NULL
      AND clpr_nombre ILIKE '%Instituciones Prestadoras%'
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN ips   ON gm.dep_codigo = ips.geo_dep_codigo AND gm.mun_codigo = ips.geo_mun_codigo")
        select_extra += ['ips.ips_total', 'ips.ips_publica', 'ips.ips_privada', 'ips.ips_mixta']
    else:
        select_extra += [
            'NULL::BIGINT AS ips_total', 'NULL::BIGINT AS ips_publica',
            'NULL::BIGINT AS ips_privada', 'NULL::BIGINT AS ips_mixta',
        ]

    # ── Capacidad instalada ──────────────────────────────────────────────────
    if ev.get('v_reps_capacidad'):
        ctefile.append(('cap', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           SUM(TRY_CAST(cantidad AS DOUBLE)) AS capacidad_instalada,
           {_CAP_TYPES}
    FROM v_reps_capacidad
    WHERE geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN cap   ON gm.dep_codigo = cap.geo_dep_codigo AND gm.mun_codigo = cap.geo_mun_codigo")
        select_extra += ['cap.capacidad_instalada', *(f'cap.{c}' for c in _CAP_COLS)]
    else:
        select_extra += ['NULL::DOUBLE AS capacidad_instalada',
                         *(f'NULL::DOUBLE AS {c}' for c in _CAP_COLS)]

    # ── Afiliación (latest month published) ──────────────────────────────────
    if ev.get('v_afiliacion'):
        ctefile.append(('afil', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           afiliados_subsidiado, afiliados_contributivo, afiliados_total,
           TRY_CAST(Cobertura AS DOUBLE) * 100 AS cobertura_pct,
           {_SISBEN_MUN},
           {_MES_LABEL} AS periodo_afiliacion
    FROM ({_afil_latest(year, month, caps)})"""))
        join_clauses.append("LEFT JOIN afil  ON gm.dep_codigo = afil.geo_dep_codigo AND gm.mun_codigo = afil.geo_mun_codigo")
        select_extra += [
            'afil.afiliados_subsidiado', 'afil.afiliados_contributivo', 'afil.afiliados_total',
            'afil.cobertura_pct', *(f'afil.{c}' for c in _SISBEN_COLS), 'afil.periodo_afiliacion',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS afiliados_subsidiado', 'NULL::BIGINT AS afiliados_contributivo',
            'NULL::BIGINT AS afiliados_total', 'NULL::DOUBLE AS cobertura_pct',
            *(f'NULL::BIGINT AS {c}' for c in _SISBEN_COLS),
            'NULL::VARCHAR AS periodo_afiliacion',
        ]

    # ── IPS / EPS intervenidas (dept-only → NULL en vista municipio) ─────────
    select_extra += [
        'NULL::BIGINT AS ips_intervenidas',
        'NULL::BIGINT AS eps_intervenidas',
    ]

    # ── EPS con afiliados en el municipio (BDUA, foto vigente) ──────────────
    if ev.get('v_bdua_eps'):
        ctefile.append(('eps', _eps_counts('geo_dep_codigo, geo_mun_codigo', 'geo_mun_codigo IS NOT NULL')))
        join_clauses.append("LEFT JOIN eps   ON gm.dep_codigo = eps.geo_dep_codigo AND gm.mun_codigo = eps.geo_mun_codigo")
        select_extra += [f'eps.{c}' for c in _EPS_COLS]
    else:
        select_extra += ['NULL::BIGINT AS eps_total', 'NULL::BIGINT AS eps_contributivo',
                         'NULL::BIGINT AS eps_subsidiado', 'NULL::VARCHAR AS eps_fecha_corte']

    # ── IRCA (latest measurement per municipality, ≤ 12 months old) ──────────
    if ev.get('v_irca'):
        ctefile.append(('irca', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           promedio_irca   AS irca_promedio,
           nivel_riesgo    AS irca_nivel_riesgo,
           {_MES_LABEL}    AS irca_periodo
    FROM ({_irca_latest_per_mun(year, month, caps)})"""))
        join_clauses.append("LEFT JOIN irca  ON gm.dep_codigo = irca.geo_dep_codigo AND gm.mun_codigo = irca.geo_mun_codigo")
        select_extra += ['irca.irca_promedio', 'irca.irca_nivel_riesgo', 'irca.irca_periodo']
    else:
        select_extra += ['NULL::DOUBLE AS irca_promedio', 'NULL::VARCHAR AS irca_nivel_riesgo',
                         'NULL::VARCHAR AS irca_periodo']

    # ── Mortalidad materna (mun-level rows, latest bulletin) ─────────────────
    if ev.get('v_ins_mortalidad_materna'):
        ctefile.append(('mm', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('razon_mm_actual')} AS razon_mortalidad_materna,
           {_PE_LABEL}              AS periodo_mortalidad_materna
    FROM ({ins('v_ins_mortalidad_materna', 'geo_mun_codigo IS NOT NULL',
                   'geo_mun_codigo', 'razon_mm_actual DESC NULLS LAST')})"""))
        # Districts appear as entity rows (entidad_territorial), not municipal rows
        ctefile.append(('mm_dist', f"""
    SELECT geo_distrito_codigo,
           {_dd('razon_mm_actual')} AS razon_mortalidad_materna,
           {_PE_LABEL}              AS periodo_mortalidad_materna
    FROM ({ins('v_ins_mortalidad_materna', f'{_DISTRICT_ROW} AND geo_mun_codigo IS NULL',
                   'geo_distrito_codigo', 'razon_mm_actual DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN mm    ON gm.dep_codigo = mm.geo_dep_codigo AND gm.mun_codigo = mm.geo_mun_codigo")
        join_clauses.append("LEFT JOIN mm_dist ON gm.mun_codigo = mm_dist.geo_distrito_codigo")
        select_extra += [
            'COALESCE(mm.razon_mortalidad_materna, mm_dist.razon_mortalidad_materna) AS razon_mortalidad_materna',
            'COALESCE(mm.periodo_mortalidad_materna, mm_dist.periodo_mortalidad_materna) AS periodo_mortalidad_materna',
        ]
    else:
        select_extra += ['NULL::DOUBLE AS razon_mortalidad_materna',
                         'NULL::VARCHAR AS periodo_mortalidad_materna']

    # ── Sífilis congénita (dept-only → NULL in municipio view) ──────────────
    # Source is the entidad territorial table (dept-level); no municipality-level data.
    select_extra.append('NULL::DOUBLE AS incidencia_sifilis_congenita')

    # ── Desnutrición aguda (mun-level, latest bulletin) ──────────────────────
    if ev.get('v_ins_desnutricion_aguda'):
        ctefile.append(('dnt', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('prevalencia_por_100')} AS prevalencia_desnutricion_aguda,
           {_PE_LABEL}                  AS periodo_desnutricion
    FROM ({ins('v_ins_desnutricion_aguda', 'geo_mun_codigo IS NOT NULL',
                   'geo_mun_codigo', 'casos DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN dnt   ON gm.dep_codigo = dnt.geo_dep_codigo AND gm.mun_codigo = dnt.geo_mun_codigo")
        select_extra += ['dnt.prevalencia_desnutricion_aguda', 'dnt.periodo_desnutricion']
    else:
        select_extra += ['NULL::DOUBLE AS prevalencia_desnutricion_aguda',
                         'NULL::VARCHAR AS periodo_desnutricion']

    # ── Intento suicidio (mun-level, latest bulletin) ────────────────────────
    if ev.get('v_ins_intento_suicidio'):
        ctefile.append(('sui', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('tasa')} AS tasa_intento_suicidio,
           {_PE_LABEL}   AS periodo_suicidio
    FROM ({ins('v_ins_intento_suicidio', 'geo_mun_codigo IS NOT NULL',
                   'geo_mun_codigo', 'tasa DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN sui   ON gm.dep_codigo = sui.geo_dep_codigo AND gm.mun_codigo = sui.geo_mun_codigo")
        select_extra += ['sui.tasa_intento_suicidio', 'sui.periodo_suicidio']
    else:
        select_extra += ['NULL::DOUBLE AS tasa_intento_suicidio', 'NULL::VARCHAR AS periodo_suicidio']

    # ── Entity-level INS tables: only the 5 districts have a municipal value ─
    if ev.get('v_ins_mortalidad_menores5'):
        ctefile.append(('men5', f"""
    SELECT geo_distrito_codigo,
           {_dd('tasa_dnt')} AS tasa_mortalidad_menores5_dnt,
           {_dd('tasa_ira')} AS tasa_mortalidad_menores5_ira,
           {_dd('tasa_eda')} AS tasa_mortalidad_menores5_eda,
           {_PE_LABEL}       AS periodo_menores5
    FROM ({ins('v_ins_mortalidad_menores5', _DISTRICT_ROW,
                   'geo_distrito_codigo', 'tasa_dnt DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN men5  ON gm.mun_codigo = men5.geo_distrito_codigo")
        select_extra += ['men5.tasa_mortalidad_menores5_dnt', 'men5.tasa_mortalidad_menores5_ira',
                         'men5.tasa_mortalidad_menores5_eda', 'men5.periodo_menores5']
    else:
        select_extra += ['NULL::DOUBLE AS tasa_mortalidad_menores5_dnt',
                         'NULL::DOUBLE AS tasa_mortalidad_menores5_ira',
                         'NULL::DOUBLE AS tasa_mortalidad_menores5_eda',
                         'NULL::VARCHAR AS periodo_menores5']

    if ev.get('v_ins_dengue'):
        ctefile.append(('dengue', f"""
    SELECT geo_distrito_codigo,
           {_dd('dengue_total')}       AS dengue_total,
           NULL::DOUBLE AS dengue_grave_total,   -- see _DENGUE_GRAVE_NOTE
           {_PE_LABEL}                 AS periodo_dengue
    FROM ({ins('v_ins_dengue', _DISTRICT_ROW,
                   'geo_distrito_codigo', 'dengue_total DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN dengue ON gm.mun_codigo = dengue.geo_distrito_codigo")
        inc = ('dengue.dengue_total * 100000.0 / NULLIF(dem.pob_total, 0)'
               if ev.get('v_demografico_edad_sexo') else 'NULL::DOUBLE')
        select_extra += ['dengue.dengue_total', 'dengue.dengue_grave_total',
                         f'{inc} AS incidencia_dengue_x100k',
                         f"{inc.replace('dengue.dengue_total', 'dengue.dengue_grave_total')} "
                         "AS incidencia_dengue_grave_x100k",
                         'dengue.periodo_dengue']
    else:
        select_extra += ['NULL::DOUBLE AS dengue_total', 'NULL::DOUBLE AS dengue_grave_total',
                         'NULL::DOUBLE AS incidencia_dengue_x100k',
                         'NULL::DOUBLE AS incidencia_dengue_grave_x100k', 'NULL::VARCHAR AS periodo_dengue']

    if ev.get('v_ins_violencia_genero'):
        ctefile.append(('viol', f"""
    SELECT geo_distrito_codigo,
           {_dd('violencia_fisica')}               AS violencia_fisica,
           {_dd('violencia_psicologica')}          AS violencia_psicologica,
           {_dd('negligencia_abandono')}           AS negligencia_abandono,
           {_dd('violencia_sexual')}               AS violencia_sexual,
           {_dd('violencia_genero_intrafamiliar')} AS violencia_genero_intrafamiliar,
           {_PE_LABEL}                             AS periodo_violencia
    FROM ({ins('v_ins_violencia_genero', _DISTRICT_ROW,
                   'geo_distrito_codigo', 'violencia_genero_intrafamiliar DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN viol  ON gm.mun_codigo = viol.geo_distrito_codigo")
        select_extra += ['viol.violencia_fisica', 'viol.violencia_psicologica',
                         'viol.negligencia_abandono', 'viol.violencia_sexual',
                         'viol.violencia_genero_intrafamiliar', 'viol.periodo_violencia']
    else:
        select_extra += ['NULL::DOUBLE AS violencia_fisica', 'NULL::DOUBLE AS violencia_psicologica',
                         'NULL::DOUBLE AS negligencia_abandono', 'NULL::DOUBLE AS violencia_sexual',
                         'NULL::DOUBLE AS violencia_genero_intrafamiliar',
                         'NULL::VARCHAR AS periodo_violencia']

    # Unavailable indicators
    select_extra += [
        'NULL::DOUBLE  AS lsp',
        'NULL::DOUBLE  AS vsp',
        'NULL::VARCHAR AS gestion_riesgo',
    ]

    ctes_sql = ',\n'.join(f"{name} AS ({body}" + "\n)" for name, body in ctefile)
    joins_sql = '\n'.join(join_clauses)
    select_sql = ',\n    '.join(select_extra)

    return f"""WITH
{ctes_sql}
SELECT
    gm.dep_codigo  AS geo_dep_codigo,
    gm.mun_codigo  AS geo_mun_codigo,
    gm.dep_dane    AS departamento,
    gm.mun_dane    AS municipio,
    {select_sql}
FROM geo_maestro gm
{joins_sql}
"""


# ---------------------------------------------------------------------------
# Departamento view
# ---------------------------------------------------------------------------

def _departamento_sql(ev: dict[str, bool], year: int | None = None, month: str | None = None,
                      caps: dict | None = None) -> str:
    """SELECT for one row per departamento (same scoping as _municipio_sql)."""
    pob_year = _pob_year(year)

    def ins(view, where, entity, order):
        return _latest(view, f"({where}) AND {_year_cond(year)} AND {_pe_cap(view, caps)}",
                       _PE_KEY, entity, order)

    ctefile: list[tuple[str, str]] = []
    join_clauses: list[str] = []
    select_extra: list[str] = []

    # ── Demografía (aggregate from municipios) ───────────────────────────────
    if ev.get('v_demografico_edad_sexo'):
        ctefile.append(('dem', f"""
    SELECT geo_dep_codigo,
           SUM(CASE WHEN sexo = 'HOMBRES' THEN poblacion ELSE 0 END) AS pob_hombres,
           SUM(CASE WHEN sexo = 'MUJERES' THEN poblacion ELSE 0 END) AS pob_mujeres,
           SUM(poblacion) AS pob_total
    FROM v_demografico_edad_sexo
    WHERE anio = {pob_year}
      AND geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        # Municipal population, used as weight for rates published only per municipality
        ctefile.append(('pob_mun', f"""
    SELECT geo_mun_codigo, SUM(poblacion) AS pob
    FROM v_demografico_edad_sexo
    WHERE anio = {pob_year} AND geo_mun_codigo IS NOT NULL
    GROUP BY 1"""))
        # INS department rows exclude the districts, so their rates need this denominator
        ctefile.append(('pob_sin_dist', f"""
    SELECT geo_dep_codigo, SUM(poblacion) AS pob
    FROM v_demografico_edad_sexo
    WHERE anio = {pob_year} AND geo_mun_codigo NOT IN ({_DISTRICT_CODES})
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN dem   ON gd.dep_codigo = dem.geo_dep_codigo")
        join_clauses.append("LEFT JOIN pob_sin_dist ON gd.dep_codigo = pob_sin_dist.geo_dep_codigo")
        select_extra += ['dem.pob_hombres', 'dem.pob_mujeres', 'dem.pob_total']
    else:
        select_extra += ['NULL::BIGINT AS pob_hombres', 'NULL::BIGINT AS pob_mujeres', 'NULL::BIGINT AS pob_total']

    # ── Étnico-racial (aggregate, same projection year as pob_total) ──────────
    if ev.get('v_demografico_etnico'):
        ctefile.append(('etnico', f"""
    SELECT geo_dep_codigo,
           SUM(poblacion) AS pob_etnico_total,
           SUM(CASE WHEN grupo_etnico ILIKE '%ndígen%' OR grupo_etnico ILIKE '%ndigen%'
                    THEN poblacion ELSE 0 END) AS pob_indigena,
           SUM(CASE WHEN grupo_etnico ILIKE '%itana%' OR grupo_etnico ILIKE '%rrom%'
                    THEN poblacion ELSE 0 END) AS pob_gitana_rrom,
           SUM(CASE WHEN grupo_etnico ILIKE '%aizal%'
                    THEN poblacion ELSE 0 END) AS pob_raizal,
           SUM(CASE WHEN grupo_etnico ILIKE '%alenquer%'
                    THEN poblacion ELSE 0 END) AS pob_palenquera,
           SUM(CASE WHEN grupo_etnico ILIKE '%egra%' OR grupo_etnico ILIKE '%fro%'
                    THEN poblacion ELSE 0 END) AS pob_negra_afro,
           SUM(CASE WHEN grupo_etnico ILIKE '%ingún%' OR grupo_etnico ILIKE '%ningun%'
                    THEN poblacion ELSE 0 END) AS pob_ninguno
    FROM v_demografico_etnico
    WHERE anio = {pob_year}
      AND geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN etnico ON gd.dep_codigo = etnico.geo_dep_codigo")
        select_extra += [
            'etnico.pob_etnico_total', 'etnico.pob_indigena', 'etnico.pob_gitana_rrom',
            'etnico.pob_raizal', 'etnico.pob_palenquera', 'etnico.pob_negra_afro', 'etnico.pob_ninguno',
            'etnico.pob_etnico_total - etnico.pob_ninguno AS pob_con_pertenencia',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS pob_etnico_total', 'NULL::BIGINT AS pob_indigena',
            'NULL::BIGINT AS pob_gitana_rrom', 'NULL::BIGINT AS pob_raizal',
            'NULL::BIGINT AS pob_palenquera', 'NULL::BIGINT AS pob_negra_afro',
            'NULL::BIGINT AS pob_ninguno', 'NULL::BIGINT AS pob_con_pertenencia',
        ]

    # ── IPS habilitadas (aggregate) ──────────────────────────────────────────
    if ev.get('v_reps_prestadores'):
        ctefile.append(('ips', """
    SELECT geo_dep_codigo,
           COUNT(*) AS ips_total,
           COUNT(CASE WHEN naju_nombre ILIKE '%ública%' THEN 1 END) AS ips_publica,
           COUNT(CASE WHEN naju_nombre ILIKE '%rivada%' THEN 1 END) AS ips_privada,
           COUNT(CASE WHEN naju_nombre ILIKE '%ixta%'   THEN 1 END) AS ips_mixta
    FROM v_reps_prestadores
    WHERE geo_dep_codigo IS NOT NULL
      AND clpr_nombre ILIKE '%Instituciones Prestadoras%'
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN ips   ON gd.dep_codigo = ips.geo_dep_codigo")
        select_extra += ['ips.ips_total', 'ips.ips_publica', 'ips.ips_privada', 'ips.ips_mixta']
    else:
        select_extra += [
            'NULL::BIGINT AS ips_total', 'NULL::BIGINT AS ips_publica',
            'NULL::BIGINT AS ips_privada', 'NULL::BIGINT AS ips_mixta',
        ]

    # ── Capacidad instalada (aggregate) ─────────────────────────────────────
    if ev.get('v_reps_capacidad'):
        ctefile.append(('cap', f"""
    SELECT geo_dep_codigo,
           SUM(TRY_CAST(cantidad AS DOUBLE)) AS capacidad_instalada,
           {_CAP_TYPES}
    FROM v_reps_capacidad
    WHERE geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN cap   ON gd.dep_codigo = cap.geo_dep_codigo")
        select_extra += ['cap.capacidad_instalada', *(f'cap.{c}' for c in _CAP_COLS)]
    else:
        select_extra += ['NULL::DOUBLE AS capacidad_instalada',
                         *(f'NULL::DOUBLE AS {c}' for c in _CAP_COLS)]

    # ── IPS intervenidas (Supersalud, dept-level) ────────────────────────────
    if ev.get('v_supersalud_ips_intervenidas'):
        ctefile.append(('ips_interv', """
    SELECT geo_dep_codigo, COUNT(*) AS ips_intervenidas
    FROM v_supersalud_ips_intervenidas
    WHERE geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN ips_interv ON gd.dep_codigo = ips_interv.geo_dep_codigo")
        # No row means no intervened entity in the department: 0, not missing
        select_extra.append('COALESCE(ips_interv.ips_intervenidas, 0) AS ips_intervenidas')
    else:
        select_extra.append('NULL::BIGINT AS ips_intervenidas')

    # ── EPS intervenidas (Supersalud, dept-level) ────────────────────────────
    if ev.get('v_supersalud_eps_intervenidas'):
        ctefile.append(('eps_interv', """
    SELECT geo_dep_codigo, COUNT(*) AS eps_intervenidas
    FROM v_supersalud_eps_intervenidas
    WHERE geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN eps_interv ON gd.dep_codigo = eps_interv.geo_dep_codigo")
        select_extra.append('COALESCE(eps_interv.eps_intervenidas, 0) AS eps_intervenidas')
    else:
        select_extra.append('NULL::BIGINT AS eps_intervenidas')

    # ── EPS con afiliados en el departamento (BDUA) ──────────────────────────
    if ev.get('v_bdua_eps'):
        ctefile.append(('eps', _eps_counts('geo_dep_codigo', 'geo_dep_codigo IS NOT NULL')))
        join_clauses.append("LEFT JOIN eps   ON gd.dep_codigo = eps.geo_dep_codigo")
        select_extra += [f'eps.{c}' for c in _EPS_COLS]
    else:
        select_extra += ['NULL::BIGINT AS eps_total', 'NULL::BIGINT AS eps_contributivo',
                         'NULL::BIGINT AS eps_subsidiado', 'NULL::VARCHAR AS eps_fecha_corte']

    # ── Afiliación (latest month, summed; coverage = Σafiliados / Σpoblación) ─
    # MinSalud caps municipal Cobertura at 100 %; the department ratio is capped
    # the same way so both levels read alike.
    if ev.get('v_afiliacion'):
        ctefile.append(('afil', f"""
    SELECT geo_dep_codigo,
           SUM(afiliados_subsidiado)   AS afiliados_subsidiado,
           SUM(afiliados_contributivo) AS afiliados_contributivo,
           SUM(afiliados_total)        AS afiliados_total,
           LEAST(100.0, 100.0 * SUM(afiliados_total)
                 / NULLIF(SUM(TRY_CAST("Población" AS DOUBLE)), 0)) AS cobertura_pct,
           {_SISBEN_SUM},
           ANY_VALUE({_MES_LABEL})     AS periodo_afiliacion
    FROM ({_afil_latest(year, month, caps)})
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN afil  ON gd.dep_codigo = afil.geo_dep_codigo")
        select_extra += [
            'afil.afiliados_subsidiado', 'afil.afiliados_contributivo', 'afil.afiliados_total',
            'afil.cobertura_pct', *(f'afil.{c}' for c in _SISBEN_COLS), 'afil.periodo_afiliacion',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS afiliados_subsidiado', 'NULL::BIGINT AS afiliados_contributivo',
            'NULL::BIGINT AS afiliados_total', 'NULL::DOUBLE AS cobertura_pct',
            *(f'NULL::BIGINT AS {c}' for c in _SISBEN_COLS),
            'NULL::VARCHAR AS periodo_afiliacion',
        ]

    # ── IRCA (weighted by number of samples) ─────────────────────────────────
    if ev.get('v_irca'):
        ctefile.append(('irca', f"""
    SELECT geo_dep_codigo,
           SUM(promedio_irca * n_muestras) / NULLIF(SUM(n_muestras), 0) AS irca_promedio,
           MAX({_MES_LABEL})                                            AS irca_periodo
    FROM ({_irca_latest_per_mun(year, month, caps)})
    WHERE promedio_irca IS NOT NULL AND n_muestras > 0
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN irca  ON gd.dep_codigo = irca.geo_dep_codigo")
        select_extra += ['irca.irca_promedio', 'irca.irca_periodo']
    else:
        select_extra += ['NULL::DOUBLE AS irca_promedio', 'NULL::VARCHAR AS irca_periodo']

    # ── Mortalidad materna — the department's own row (no districts) ─────────
    if ev.get('v_ins_mortalidad_materna'):
        ctefile.append(('mm', f"""
    SELECT geo_dep_codigo,
           {_dd('razon_mm_actual')} AS razon_mortalidad_materna,
           {_PE_LABEL}              AS periodo_mortalidad_materna
    FROM ({ins('v_ins_mortalidad_materna', _DEPT_ROW,
                   'geo_dep_codigo', 'razon_mm_actual DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN mm    ON gd.dep_codigo = mm.geo_dep_codigo")
        select_extra += ['mm.razon_mortalidad_materna', 'mm.periodo_mortalidad_materna']
    else:
        select_extra += ['NULL::DOUBLE AS razon_mortalidad_materna',
                         'NULL::VARCHAR AS periodo_mortalidad_materna']

    # ── Sífilis congénita (department's own row) ─────────────────────────────
    # casos_sc_total = NV + MF total SC cases. Incidence rate not in extracted data → NULL.
    if ev.get('v_ins_sifilis_congenita'):
        sc_where = f"{_DEPT_ROW} AND casos_sc_total IS NOT NULL AND casos_sc_total != ''"
        ctefile.append(('sc', f"""
    SELECT geo_dep_codigo,
           {_di('casos_sc_total')} AS casos_sifilis_congenita,
           NULL::DOUBLE            AS incidencia_sifilis_congenita,
           {_PE_LABEL}             AS periodo_sifilis
    FROM ({ins('v_ins_sifilis_congenita', sc_where,
                   'geo_dep_codigo', 'casos_sc_total DESC')})"""))
        join_clauses.append("LEFT JOIN sc    ON gd.dep_codigo = sc.geo_dep_codigo")
        select_extra += ['sc.casos_sifilis_congenita', 'sc.incidencia_sifilis_congenita',
                         'sc.periodo_sifilis']
    else:
        select_extra += ['NULL::BIGINT AS casos_sifilis_congenita',
                         'NULL::DOUBLE AS incidencia_sifilis_congenita',
                         'NULL::VARCHAR AS periodo_sifilis']

    # ── Desnutrición aguda (municipios listed in the latest bulletin) ────────
    # Prevalence is weighted: each municipality's denominator is implied by
    # casos / (prevalencia/100), so the result is Σcasos / Σdenominador · 100.
    # The bulletin lists only some municipalities: desnutricion_municipios_reportados.
    if ev.get('v_ins_desnutricion_aguda'):
        ctefile.append(('dnt', f"""
    SELECT geo_dep_codigo,
           SUM(c)                                                    AS casos_desnutricion_aguda,
           100.0 * SUM(c) FILTER (WHERE p > 0) / NULLIF(SUM(c / (p / 100.0)) FILTER (WHERE p > 0), 0)
                                                                     AS prevalencia_desnutricion_aguda,
           COUNT(*)                                                  AS desnutricion_municipios_reportados,
           ANY_VALUE(periodo)                                        AS periodo_desnutricion
    FROM (
        SELECT geo_dep_codigo, {_di('casos')} AS c, {_dd('prevalencia_por_100')} AS p,
               {_PE_LABEL} AS periodo
        FROM ({ins('v_ins_desnutricion_aguda', 'geo_mun_codigo IS NOT NULL',
                       'geo_mun_codigo', 'casos DESC NULLS LAST')})
    )
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN dnt   ON gd.dep_codigo = dnt.geo_dep_codigo")
        select_extra += ['dnt.casos_desnutricion_aguda', 'dnt.prevalencia_desnutricion_aguda',
                         'dnt.desnutricion_municipios_reportados', 'dnt.periodo_desnutricion']
    else:
        select_extra += ['NULL::BIGINT AS casos_desnutricion_aguda',
                         'NULL::DOUBLE AS prevalencia_desnutricion_aguda',
                         'NULL::BIGINT AS desnutricion_municipios_reportados',
                         'NULL::VARCHAR AS periodo_desnutricion']

    # ── Mortalidad menores 5 (department's own row) ──────────────────────────
    if ev.get('v_ins_mortalidad_menores5'):
        ctefile.append(('men5', f"""
    SELECT geo_dep_codigo,
           {_dd('tasa_dnt')} AS tasa_mortalidad_menores5_dnt,
           {_dd('tasa_ira')} AS tasa_mortalidad_menores5_ira,
           {_dd('tasa_eda')} AS tasa_mortalidad_menores5_eda,
           {_PE_LABEL}       AS periodo_menores5
    FROM ({ins('v_ins_mortalidad_menores5', _DEPT_ROW,
                   'geo_dep_codigo', 'tasa_dnt DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN men5  ON gd.dep_codigo = men5.geo_dep_codigo")
        select_extra += [
            'men5.tasa_mortalidad_menores5_dnt',
            'men5.tasa_mortalidad_menores5_ira',
            'men5.tasa_mortalidad_menores5_eda',
            'men5.periodo_menores5',
        ]
    else:
        select_extra += [
            'NULL::DOUBLE AS tasa_mortalidad_menores5_dnt',
            'NULL::DOUBLE AS tasa_mortalidad_menores5_ira',
            'NULL::DOUBLE AS tasa_mortalidad_menores5_eda',
            'NULL::VARCHAR AS periodo_menores5',
        ]

    # ── Dengue (department's own row) ────────────────────────────────────────
    if ev.get('v_ins_dengue'):
        ctefile.append(('dengue', f"""
    SELECT geo_dep_codigo,
           {_dd('dengue_total')}       AS dengue_total,
           NULL::DOUBLE AS dengue_grave_total,   -- see _DENGUE_GRAVE_NOTE
           {_PE_LABEL}                 AS periodo_dengue
    FROM ({ins('v_ins_dengue', _DEPT_ROW,
                   'geo_dep_codigo', 'dengue_total DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN dengue ON gd.dep_codigo = dengue.geo_dep_codigo")
        inc = ('dengue.dengue_total * 100000.0 / NULLIF(pob_sin_dist.pob, 0)'
               if ev.get('v_demografico_edad_sexo') else 'NULL::DOUBLE')
        select_extra += ['dengue.dengue_total', 'dengue.dengue_grave_total',
                         f'{inc} AS incidencia_dengue_x100k',
                         f"{inc.replace('dengue.dengue_total', 'dengue.dengue_grave_total')} "
                         "AS incidencia_dengue_grave_x100k",
                         'dengue.periodo_dengue']
    else:
        select_extra += [
            'NULL::DOUBLE AS dengue_total', 'NULL::DOUBLE AS dengue_grave_total',
            'NULL::DOUBLE AS incidencia_dengue_x100k',
            'NULL::DOUBLE AS incidencia_dengue_grave_x100k', 'NULL::VARCHAR AS periodo_dengue',
        ]

    # ── Intento suicidio (municipios listed, weighted by DANE population) ────
    # tasa = casos / población · 100k, so Σ(tasa·pob) / Σpob is the pooled rate
    # of the municipalities in the bulletin (suicidio_municipios_reportados).
    if ev.get('v_ins_intento_suicidio') and ev.get('v_demografico_edad_sexo'):
        ctefile.append(('sui', f"""
    SELECT s.geo_dep_codigo,
           SUM({_dd('s.tasa')} * p.pob) / NULLIF(SUM(p.pob), 0) AS tasa_intento_suicidio,
           COUNT(*)                                              AS suicidio_municipios_reportados,
           ANY_VALUE(CAST(s.anio AS VARCHAR) || ' PE ' || s.periodo_epidemiologico) AS periodo_suicidio
    FROM ({ins('v_ins_intento_suicidio', 'geo_mun_codigo IS NOT NULL',
                   'geo_mun_codigo', 'tasa DESC NULLS LAST')}) s
    JOIN pob_mun p ON p.geo_mun_codigo = s.geo_mun_codigo
    WHERE {_dd('s.tasa')} IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN sui   ON gd.dep_codigo = sui.geo_dep_codigo")
        select_extra += ['sui.tasa_intento_suicidio', 'sui.suicidio_municipios_reportados',
                         'sui.periodo_suicidio']
    else:
        select_extra += ['NULL::DOUBLE AS tasa_intento_suicidio',
                         'NULL::BIGINT AS suicidio_municipios_reportados',
                         'NULL::VARCHAR AS periodo_suicidio']

    # ── Violencia de género (department's own row) ───────────────────────────
    if ev.get('v_ins_violencia_genero'):
        ctefile.append(('viol', f"""
    SELECT geo_dep_codigo,
           {_dd('violencia_fisica')}               AS violencia_fisica,
           {_dd('violencia_psicologica')}          AS violencia_psicologica,
           {_dd('negligencia_abandono')}           AS negligencia_abandono,
           {_dd('violencia_sexual')}               AS violencia_sexual,
           {_dd('violencia_genero_intrafamiliar')} AS violencia_genero_intrafamiliar,
           {_PE_LABEL}                             AS periodo_violencia
    FROM ({ins('v_ins_violencia_genero', _DEPT_ROW,
                   'geo_dep_codigo', 'violencia_genero_intrafamiliar DESC NULLS LAST')})"""))
        join_clauses.append("LEFT JOIN viol  ON gd.dep_codigo = viol.geo_dep_codigo")
        select_extra += [
            'viol.violencia_fisica', 'viol.violencia_psicologica', 'viol.negligencia_abandono',
            'viol.violencia_sexual', 'viol.violencia_genero_intrafamiliar', 'viol.periodo_violencia',
        ]
    else:
        select_extra += [
            'NULL::DOUBLE AS violencia_fisica', 'NULL::DOUBLE AS violencia_psicologica',
            'NULL::DOUBLE AS negligencia_abandono', 'NULL::DOUBLE AS violencia_sexual',
            'NULL::DOUBLE AS violencia_genero_intrafamiliar', 'NULL::VARCHAR AS periodo_violencia',
        ]

    select_extra += [
        'NULL::DOUBLE  AS lsp',
        'NULL::DOUBLE  AS vsp',
        'NULL::VARCHAR AS gestion_riesgo',
    ]

    ctes_sql = ',\n'.join(f"{name} AS ({body}" + "\n)" for name, body in ctefile)
    joins_sql = '\n'.join(join_clauses)
    select_sql = ',\n    '.join(select_extra)

    return f"""WITH
{ctes_sql}
SELECT
    gd.dep_codigo  AS geo_dep_codigo,
    gd.dep_dane    AS departamento,
    {select_sql}
FROM geo_dep gd
{joins_sql}
"""


# ---------------------------------------------------------------------------
# National view (one row) — the reference the dashboard compares against
# ---------------------------------------------------------------------------

def _nacional_sql(ev: dict[str, bool], year: int | None = None, month: str | None = None,
                  caps: dict | None = None) -> str:
    """One row of national rates, same column names as the department view.

    INS rates come from the bulletin's own 'Colombia' row; the rest are pooled
    nationally (Σnumerador / Σdenominador). Counts that only make sense per
    territory (IPS, cases) are left to the dashboard as departmental averages.
    """
    pob_year = _pob_year(year)

    def ins(view, where, order):
        return _latest(view, f"({where}) AND {_year_cond(year)} AND {_pe_cap(view, caps)}",
                       _PE_KEY, "'colombia'", order)

    parts: list[tuple[str, str, list[str]]] = []   # (cte name, body, columns)

    if ev.get('v_demografico_edad_sexo'):
        parts.append(('dem', f"""
    SELECT SUM(poblacion) AS pob_total
    FROM v_demografico_edad_sexo WHERE anio = {pob_year} AND geo_mun_codigo IS NOT NULL""",
                      ['pob_total']))
    if ev.get('v_afiliacion'):
        parts.append(('afil', f"""
    SELECT LEAST(100.0, 100.0 * SUM(afiliados_total)
                 / NULLIF(SUM(TRY_CAST("Población" AS DOUBLE)), 0)) AS cobertura_pct,
           SUM(afiliados_subsidiado) AS afiliados_subsidiado,
           SUM(afiliados_contributivo) AS afiliados_contributivo,
           {_SISBEN_SUM},
           ANY_VALUE({_MES_LABEL}) AS periodo_afiliacion
    FROM ({_afil_latest(year, month, caps)})""",
                      ['cobertura_pct', 'afiliados_subsidiado', 'afiliados_contributivo',
                       *_SISBEN_COLS, 'periodo_afiliacion']))
    if ev.get('v_bdua_eps'):
        parts.append(('eps', _eps_counts('', 'TRUE'), list(_EPS_COLS)))
    if ev.get('v_reps_capacidad'):
        parts.append(('cap', f"""
    SELECT {_CAP_TYPES}
    FROM v_reps_capacidad WHERE geo_mun_codigo IS NOT NULL""", list(_CAP_COLS)))
    if ev.get('v_irca'):
        parts.append(('irca', f"""
    SELECT SUM(promedio_irca * n_muestras) / NULLIF(SUM(n_muestras), 0) AS irca_promedio
    FROM ({_irca_latest_per_mun(year, month, caps)})
    WHERE promedio_irca IS NOT NULL AND n_muestras > 0""", ['irca_promedio']))
    if ev.get('v_ins_mortalidad_materna'):
        parts.append(('mm', f"""
    SELECT {_dd('razon_mm_actual')} AS razon_mortalidad_materna,
           {_PE_LABEL} AS periodo_mortalidad_materna
    FROM ({ins('v_ins_mortalidad_materna', _COUNTRY_ROW, 'razon_mm_actual DESC NULLS LAST')})""",
                      ['razon_mortalidad_materna', 'periodo_mortalidad_materna']))
    if ev.get('v_ins_desnutricion_aguda'):
        parts.append(('dnt', f"""
    SELECT 100.0 * SUM(c) FILTER (WHERE p > 0) / NULLIF(SUM(c / (p / 100.0)) FILTER (WHERE p > 0), 0)
               AS prevalencia_desnutricion_aguda,
           ANY_VALUE(periodo) AS periodo_desnutricion
    FROM (
        SELECT {_di('casos')} AS c, {_dd('prevalencia_por_100')} AS p, {_PE_LABEL} AS periodo
        FROM ({_latest('v_ins_desnutricion_aguda', f"geo_mun_codigo IS NOT NULL AND {_year_cond(year)} "
                       f"AND {_pe_cap('v_ins_desnutricion_aguda', caps)}",
                       _PE_KEY, 'geo_mun_codigo', 'casos DESC NULLS LAST')})
    )""", ['prevalencia_desnutricion_aguda', 'periodo_desnutricion']))
    if ev.get('v_ins_mortalidad_menores5'):
        parts.append(('men5', f"""
    SELECT {_dd('tasa_dnt')} AS tasa_mortalidad_menores5_dnt,
           {_dd('tasa_ira')} AS tasa_mortalidad_menores5_ira,
           {_dd('tasa_eda')} AS tasa_mortalidad_menores5_eda,
           {_PE_LABEL}       AS periodo_menores5
    FROM ({ins('v_ins_mortalidad_menores5', _COUNTRY_ROW, 'tasa_dnt DESC NULLS LAST')})""",
                      ['tasa_mortalidad_menores5_dnt', 'tasa_mortalidad_menores5_ira',
                       'tasa_mortalidad_menores5_eda', 'periodo_menores5']))
    if ev.get('v_ins_dengue') and ev.get('v_demografico_edad_sexo'):
        parts.append(('dengue', f"""
    SELECT {_dd('dengue_total')} * 100000.0
               / (SELECT SUM(poblacion) FROM v_demografico_edad_sexo
                  WHERE anio = {pob_year} AND geo_mun_codigo IS NOT NULL) AS incidencia_dengue_x100k,
           NULL::DOUBLE AS incidencia_dengue_grave_x100k,   -- see _DENGUE_GRAVE_NOTE
           {_PE_LABEL} AS periodo_dengue
    FROM ({ins('v_ins_dengue', _COUNTRY_ROW, 'dengue_total DESC NULLS LAST')})""",
                      ['incidencia_dengue_x100k', 'incidencia_dengue_grave_x100k', 'periodo_dengue']))
    if ev.get('v_ins_intento_suicidio') and ev.get('v_demografico_edad_sexo'):
        parts.append(('sui', f"""
    SELECT SUM({_dd('s.tasa')} * p.pob) / NULLIF(SUM(p.pob), 0) AS tasa_intento_suicidio,
           ANY_VALUE(CAST(s.anio AS VARCHAR) || ' PE ' || s.periodo_epidemiologico) AS periodo_suicidio
    FROM ({_latest('v_ins_intento_suicidio', f"geo_mun_codigo IS NOT NULL AND {_year_cond(year)} "
                   f"AND {_pe_cap('v_ins_intento_suicidio', caps)}",
                   _PE_KEY, 'geo_mun_codigo', 'tasa DESC NULLS LAST')}) s
    JOIN (SELECT geo_mun_codigo, SUM(poblacion) AS pob FROM v_demografico_edad_sexo
          WHERE anio = {pob_year} GROUP BY 1) p ON p.geo_mun_codigo = s.geo_mun_codigo
    WHERE {_dd('s.tasa')} IS NOT NULL""", ['tasa_intento_suicidio', 'periodo_suicidio']))
    if ev.get('v_ins_violencia_genero'):
        parts.append(('viol', f"""
    SELECT {_dd('violencia_fisica')}      AS violencia_fisica,
           {_dd('violencia_psicologica')} AS violencia_psicologica,
           {_dd('negligencia_abandono')}  AS negligencia_abandono,
           {_dd('violencia_sexual')}      AS violencia_sexual,
           {_PE_LABEL}                    AS periodo_violencia
    FROM ({ins('v_ins_violencia_genero', _COUNTRY_ROW, 'violencia_fisica DESC NULLS LAST')})""",
                      ['violencia_fisica', 'violencia_psicologica', 'negligencia_abandono',
                       'violencia_sexual', 'periodo_violencia']))

    if not parts:
        return "SELECT NULL::DOUBLE AS pob_total"
    ctes = ',\n'.join(f'{name} AS ({body}\n)' for name, body, _ in parts)
    cols = ', '.join(f'{name}.{c}' for name, _, cs in parts for c in cs)
    # Each CTE yields at most one row; LEFT JOIN ON TRUE keeps the row when one is empty
    base, *rest = [name for name, _, _ in parts]
    joins = ' '.join(f'LEFT JOIN {name} ON TRUE' for name in rest)
    return f"WITH {ctes}\nSELECT {cols} FROM {base} {joins}"


# ---------------------------------------------------------------------------
# Per-period tables for the dashboard's year / month selectors
# ---------------------------------------------------------------------------

def _period_grid(con: duckdb.DuckDBPyConnection) -> list[tuple[int, str | None]]:
    """Every (year, month) the dashboard offers: each year with data in a time-varying
    source, as 'latest in that year' (month None) plus each afiliación month of it."""
    years: set[int] = set()
    for t in ('afiliacion', 'irca', 'ins_dengue', 'ins_mortalidad_materna'):
        try:
            years |= {int(r[0]) for r in con.execute(
                f'SELECT DISTINCT anio FROM {t} WHERE anio IS NOT NULL').fetchall()}
        except duckdb.CatalogException:
            pass
    grid: list[tuple[int, str | None]] = []
    for y in sorted(years, reverse=True):
        grid.append((y, None))
        try:
            months = {r[0] for r in con.execute(
                'SELECT DISTINCT UPPER(TRIM(mes)) FROM afiliacion WHERE anio = ?', [y]).fetchall()}
        except duckdb.CatalogException:
            months = set()
        grid += [(y, m) for m in _MESES if m in months]
    return grid


def _build_period_tables(con: duckdb.DuckDBPyConnection, ev: dict[str, bool]) -> None:
    """metricas_{municipio,departamento,nacional}_periodo: the same metrics as the views, once
    per (anio_filtro, mes_filtro). mes_filtro NULL = latest data within the year.

    The dashboard reads these rows instead of re-deriving metrics in its own SQL, so
    the pipeline is the single source of truth for every number shown.
    """
    grid = _period_grid(con)
    years = {y for y, _ in grid}
    # Same period one year earlier, for "tendencia vs. año anterior" (FCT): each
    # source capped at the period the current selection actually shows, e.g.
    # 2026 PE IX is compared with 2025 PE IX, not with the whole of 2025.
    prev = [(y, m, _resolve_caps(con, ev, y, m)) for y, m in grid if y - 1 in years]
    for level, build in (('municipio', _municipio_sql), ('departamento', _departamento_sql),
                         ('nacional', _nacional_sql)):
        for table, rows in ((f'metricas_{level}_periodo', [(y, m, y, m, None) for y, m in grid]),
                            (f'metricas_{level}_anterior', [(y, m, y - 1, None, c) for y, m, c in prev])):
            if not rows:
                con.execute(f"DROP TABLE IF EXISTS {table}")
                continue
            parts = [
                f"SELECT {ky} AS anio_filtro, "
                f"{'NULL' if km is None else repr(km)}::VARCHAR AS mes_filtro, * "
                f"FROM ({build(ev, y, m, caps)})"
                for ky, km, y, m, caps in rows
            ]
            con.execute(f"CREATE OR REPLACE TABLE {table} AS " + "\nUNION ALL BY NAME\n".join(parts))
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f'  {table}: {n:,} filas ({len(rows)} periodos)')


_EDAD_ORDEN = {'< 1': 0, '1 a 5': 1, '5 a 15': 2, '15 a 19': 3, '19 a 45': 4, '45 a 50': 5,
               '50 a 55': 6, '55 a 60': 7, '60 a 65': 8, '65 a 70': 9, '70 a 75': 10, '> 75': 11}


def _build_piramide(con: duckdb.DuckDBPyConnection) -> None:
    """piramide_afiliados: affiliates by regime × sex × age group (BDUA) for every
    municipality, department and the nation (nivel / codigo; nación = codigo 0)."""
    orden = ' '.join(f"WHEN '{k}' THEN {v}" for k, v in _EDAD_ORDEN.items())
    base = f"""SELECT regimen, sexo, grupo_edad, CASE grupo_edad {orden} ELSE 99 END AS orden_edad,
                      afiliados, fecha_corte, geo_dep_codigo, geo_mun_codigo FROM v_bdua_piramide"""
    con.execute(f"""
        CREATE OR REPLACE TABLE piramide_afiliados AS
        WITH b AS ({base})
        SELECT 'municipio' AS nivel, geo_mun_codigo AS codigo, regimen, sexo, grupo_edad, orden_edad,
               SUM(afiliados) AS afiliados, MAX(fecha_corte) AS fecha_corte
        FROM b WHERE geo_mun_codigo IS NOT NULL GROUP BY ALL
        UNION ALL
        SELECT 'departamento', geo_dep_codigo, regimen, sexo, grupo_edad, orden_edad,
               SUM(afiliados), MAX(fecha_corte)
        FROM b WHERE geo_dep_codigo IS NOT NULL GROUP BY ALL
        UNION ALL
        SELECT 'nacional', 0, regimen, sexo, grupo_edad, orden_edad, SUM(afiliados), MAX(fecha_corte)
        FROM b GROUP BY ALL""")
    n = con.execute("SELECT COUNT(*) FROM piramide_afiliados").fetchone()[0]
    print(f'  piramide_afiliados: {n:,} filas')


def _resolve_caps(con: duckdb.DuckDBPyConnection, ev: dict[str, bool],
                  year: int, month: str | None) -> dict:
    """The period each source shows for selection (year, month): the latest INS
    epidemiological period in that year, the afiliación month, the IRCA month."""
    caps: dict = {'pe': {}}
    for view in [v for v in ev if v.startswith('v_ins_') and ev[v]]:
        n = con.execute(f"SELECT MAX({_PE_CASE}) FROM {view} WHERE anio = ?", [year]).fetchone()[0]
        if n:
            caps['pe'][view] = int(n)
    if ev.get('v_afiliacion'):
        caps['afil_mes'] = month or con.execute(
            f"SELECT UPPER(TRIM(mes)) FROM afiliacion WHERE anio = ? "
            f"ORDER BY {_MES_CASE} DESC LIMIT 1", [year]).fetchone()[0]
    if ev.get('v_irca'):
        caps['irca_mes'] = (_MESES.index(month) + 1 if month else
                            con.execute(f"SELECT MAX({_MES_CASE}) FROM irca WHERE anio = ?",
                                        [year]).fetchone()[0])
    return caps


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_all(db_path: 'str | Path') -> None:
    """Create v_metricas_municipio and v_metricas_departamento in DuckDB."""
    print('metricas: construyendo vistas de métricas consolidadas...')
    db_path = Path(db_path)
    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type IN ('VIEW', 'BASE TABLE')"
        ).fetchall()
        existing = {r[0] for r in rows}

        if 'geo_maestro' not in existing:
            raise RuntimeError('metricas: geo_maestro no existe. Ejecuta transform.py primero.')

        ev = {n: n in existing for n in [
            'v_demografico_edad_sexo', 'v_demografico_etnico',
            'v_reps_prestadores', 'v_reps_capacidad',
            'v_afiliacion', 'v_irca',
            'v_ins_mortalidad_materna', 'v_ins_sifilis_congenita',
            'v_ins_desnutricion_aguda', 'v_ins_intento_suicidio',
            'v_ins_mortalidad_menores5', 'v_ins_dengue', 'v_ins_violencia_genero',
            'v_supersalud_ips_intervenidas', 'v_supersalud_eps_intervenidas',
            'v_bdua_eps', 'v_bdua_piramide',
        ]}
        missing = [k for k, v in ev.items() if not v]
        if missing:
            log.info(f'metricas: vistas no disponibles (serán NULL): {missing}')

        con.execute(f"CREATE OR REPLACE VIEW v_metricas_municipio AS {_municipio_sql(ev)}")
        con.execute(f"CREATE OR REPLACE VIEW v_metricas_departamento AS {_departamento_sql(ev)}")
        con.execute(f"CREATE OR REPLACE VIEW v_metricas_nacional AS {_nacional_sql(ev)}")
        for v in ('v_metricas_municipio', 'v_metricas_departamento', 'v_metricas_nacional'):
            n = con.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]
            print(f'  {v}: {n:,} filas')

        _build_period_tables(con, ev)
        if ev.get('v_bdua_piramide'):
            _build_piramide(con)
        print('metricas OK — vistas v_metricas_* y tablas metricas_*_periodo creadas')
    except Exception as e:
        print(f'metricas: ERROR — {e}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format='%(levelname)s %(message)s')
    _base = Path(__file__).resolve().parent.parent
    build_all(_base / 'data' / 'informe_regional.duckdb')
