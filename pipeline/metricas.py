# -*- coding: utf-8 -*-
"""
metricas.py — Vistas consolidadas de métricas de salud por municipio y departamento.

Crea:
  v_metricas_municipio    — una fila por municipio DANE con ~35 indicadores
  v_metricas_departamento — una fila por departamento con los mismos indicadores
                            (fuentes dept-only incluidas; fuentes municipio se agregan)

Requiere que geo_normalize.build_all() ya haya creado las vistas v_* y geo_maestro/geo_dep.

Run: python pipeline/metricas.py
"""

import logging
from pathlib import Path

import duckdb

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


def _dd(col: str) -> str:
    """TRY_CAST a PDF-extracted column to DOUBLE, handling Spanish decimal comma.

    Removes thousands-separator dots first, then converts decimal commas to dots.
    E.g. '2.069,0' → '2069.0' → 2069.0
    """
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '.') AS DOUBLE)"


def _di(col: str) -> str:
    """TRY_CAST a PDF-extracted column to BIGINT, stripping dots and commas."""
    return f"TRY_CAST(REPLACE(REPLACE({col}, '.', ''), ',', '') AS BIGINT)"


# ---------------------------------------------------------------------------
# Municipio view
# ---------------------------------------------------------------------------

def _build_municipio_view(con: duckdb.DuckDBPyConnection, ev: dict[str, bool]) -> None:
    """Create v_metricas_municipio."""

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
    WHERE anio = (SELECT MAX(anio) FROM demografico_edad_sexo WHERE anio <= YEAR(CURRENT_DATE))
      AND geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN dem   ON gm.dep_codigo = dem.geo_dep_codigo AND gm.mun_codigo = dem.geo_mun_codigo")
        select_extra += ['dem.pob_hombres', 'dem.pob_mujeres', 'dem.pob_total']
    else:
        select_extra += ['NULL::BIGINT AS pob_hombres', 'NULL::BIGINT AS pob_mujeres', 'NULL::BIGINT AS pob_total']

    # ── Étnico-racial ────────────────────────────────────────────────────────
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
    WHERE anio = (SELECT MAX(anio) FROM demografico_etnico)
      AND geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN etnico ON gm.dep_codigo = etnico.geo_dep_codigo AND gm.mun_codigo = etnico.geo_mun_codigo")
        select_extra += [
            'etnico.pob_etnico_total', 'etnico.pob_indigena', 'etnico.pob_gitana_rrom',
            'etnico.pob_raizal', 'etnico.pob_palenquera', 'etnico.pob_negra_afro', 'etnico.pob_ninguno',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS pob_etnico_total', 'NULL::BIGINT AS pob_indigena',
            'NULL::BIGINT AS pob_gitana_rrom', 'NULL::BIGINT AS pob_raizal',
            'NULL::BIGINT AS pob_palenquera', 'NULL::BIGINT AS pob_negra_afro',
            'NULL::BIGINT AS pob_ninguno',
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
        ctefile.append(('cap', """
    SELECT geo_dep_codigo, geo_mun_codigo,
           SUM(TRY_CAST(cantidad AS DOUBLE)) AS capacidad_instalada
    FROM v_reps_capacidad
    WHERE geo_mun_codigo IS NOT NULL
    GROUP BY 1, 2"""))
        join_clauses.append("LEFT JOIN cap   ON gm.dep_codigo = cap.geo_dep_codigo AND gm.mun_codigo = cap.geo_mun_codigo")
        select_extra.append('cap.capacidad_instalada')
    else:
        select_extra.append('NULL::DOUBLE AS capacidad_instalada')

    # ── Afiliación ───────────────────────────────────────────────────────────
    if ev.get('v_afiliacion'):
        ctefile.append(('afil_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_MES_CASE}) DESC
           ) AS rn
    FROM v_afiliacion
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('afil', """
    SELECT geo_dep_codigo, geo_mun_codigo,
           afiliados_subsidiado, afiliados_contributivo, afiliados_total,
           TRY_CAST(Cobertura AS DOUBLE) * 100 AS cobertura_pct
    FROM afil_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN afil  ON gm.dep_codigo = afil.geo_dep_codigo AND gm.mun_codigo = afil.geo_mun_codigo")
        select_extra += [
            'afil.afiliados_subsidiado', 'afil.afiliados_contributivo', 'afil.afiliados_total',
            'afil.cobertura_pct',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS afiliados_subsidiado', 'NULL::BIGINT AS afiliados_contributivo',
            'NULL::BIGINT AS afiliados_total', 'NULL::DOUBLE AS cobertura_pct',
        ]

    # ── IPS / EPS intervenidas (dept-only → NULL en vista municipio) ─────────
    select_extra += [
        'NULL::BIGINT AS ips_intervenidas',
        'NULL::BIGINT AS eps_intervenidas',
        'NULL::BIGINT AS eps_autorizadas',
    ]

    # ── IRCA ─────────────────────────────────────────────────────────────────
    if ev.get('v_irca'):
        ctefile.append(('irca_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_MES_CASE}) DESC
           ) AS rn
    FROM v_irca
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('irca', """
    SELECT geo_dep_codigo, geo_mun_codigo,
           promedio_irca   AS irca_promedio,
           nivel_riesgo    AS irca_nivel_riesgo
    FROM irca_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN irca  ON gm.dep_codigo = irca.geo_dep_codigo AND gm.mun_codigo = irca.geo_mun_codigo")
        select_extra += ['irca.irca_promedio', 'irca.irca_nivel_riesgo']
    else:
        select_extra += ['NULL::DOUBLE AS irca_promedio', 'NULL::VARCHAR AS irca_nivel_riesgo']

    # ── Mortalidad materna (mun-level) ───────────────────────────────────────
    if ev.get('v_ins_mortalidad_materna'):
        ctefile.append(('mm_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_mortalidad_materna
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('mm', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('razon_mm_actual')} AS razon_mortalidad_materna
    FROM mm_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN mm    ON gm.dep_codigo = mm.geo_dep_codigo AND gm.mun_codigo = mm.geo_mun_codigo")
        select_extra.append('mm.razon_mortalidad_materna')
    else:
        select_extra.append('NULL::DOUBLE AS razon_mortalidad_materna')

    # ── Sífilis congénita (dept-only → NULL in municipio view) ──────────────
    # Source is the entidad territorial table (dept-level); no municipality-level data.
    select_extra.append('NULL::DOUBLE AS incidencia_sifilis_congenita')

    # ── Desnutrición aguda (mun-level) ───────────────────────────────────────
    if ev.get('v_ins_desnutricion_aguda'):
        ctefile.append(('dnt_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_desnutricion_aguda
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('dnt', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('prevalencia_por_100')} AS prevalencia_desnutricion_aguda
    FROM dnt_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN dnt   ON gm.dep_codigo = dnt.geo_dep_codigo AND gm.mun_codigo = dnt.geo_mun_codigo")
        select_extra.append('dnt.prevalencia_desnutricion_aguda')
    else:
        select_extra.append('NULL::DOUBLE AS prevalencia_desnutricion_aguda')

    # ── Intento suicidio (mun-level: tasa per municipio) ─────────────────────
    if ev.get('v_ins_intento_suicidio'):
        ctefile.append(('sui_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_intento_suicidio
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('sui', f"""
    SELECT geo_dep_codigo, geo_mun_codigo,
           {_dd('tasa')} AS tasa_intento_suicidio
    FROM sui_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN sui   ON gm.dep_codigo = sui.geo_dep_codigo AND gm.mun_codigo = sui.geo_mun_codigo")
        select_extra += ['sui.tasa_intento_suicidio']
    else:
        select_extra += ['NULL::DOUBLE AS tasa_intento_suicidio']

    # ── Dept-only INS metrics → NULL in municipio view ───────────────────────
    select_extra += [
        'NULL::DOUBLE AS tasa_mortalidad_menores5_dnt',
        'NULL::DOUBLE AS tasa_mortalidad_menores5_ira',
        'NULL::DOUBLE AS tasa_mortalidad_menores5_eda',
        'NULL::DOUBLE AS dengue_total',
        'NULL::DOUBLE AS dengue_grave_total',
        'NULL::DOUBLE AS incidencia_dengue_x100k',
        'NULL::DOUBLE AS violencia_fisica',
        'NULL::DOUBLE AS violencia_psicologica',
        'NULL::DOUBLE AS negligencia_abandono',
        'NULL::DOUBLE AS violencia_sexual',
        'NULL::DOUBLE AS violencia_genero_intrafamiliar',
        # Unavailable indicators
        'NULL::DOUBLE  AS lsp',
        'NULL::DOUBLE  AS vsp',
        'NULL::VARCHAR AS gestion_riesgo',
    ]

    ctes_sql = ',\n'.join(f"{name} AS ({body}" + "\n)" for name, body in ctefile)
    joins_sql = '\n'.join(join_clauses)
    select_sql = ',\n    '.join(select_extra)

    sql = f"""CREATE OR REPLACE VIEW v_metricas_municipio AS
WITH
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
    con.execute(sql)
    n = con.execute("SELECT COUNT(*) FROM v_metricas_municipio").fetchone()[0]
    print(f'  v_metricas_municipio: {n:,} municipios')


# ---------------------------------------------------------------------------
# Departamento view
# ---------------------------------------------------------------------------

def _build_departamento_view(con: duckdb.DuckDBPyConnection, ev: dict[str, bool]) -> None:
    """Create v_metricas_departamento."""

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
    WHERE anio = (SELECT MAX(anio) FROM demografico_edad_sexo WHERE anio <= YEAR(CURRENT_DATE))
      AND geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN dem   ON gd.dep_codigo = dem.geo_dep_codigo")
        select_extra += ['dem.pob_hombres', 'dem.pob_mujeres', 'dem.pob_total']
    else:
        select_extra += ['NULL::BIGINT AS pob_hombres', 'NULL::BIGINT AS pob_mujeres', 'NULL::BIGINT AS pob_total']

    # ── Étnico-racial (aggregate) ─────────────────────────────────────────────
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
    WHERE anio = (SELECT MAX(anio) FROM demografico_etnico)
      AND geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN etnico ON gd.dep_codigo = etnico.geo_dep_codigo")
        select_extra += [
            'etnico.pob_etnico_total', 'etnico.pob_indigena', 'etnico.pob_gitana_rrom',
            'etnico.pob_raizal', 'etnico.pob_palenquera', 'etnico.pob_negra_afro', 'etnico.pob_ninguno',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS pob_etnico_total', 'NULL::BIGINT AS pob_indigena',
            'NULL::BIGINT AS pob_gitana_rrom', 'NULL::BIGINT AS pob_raizal',
            'NULL::BIGINT AS pob_palenquera', 'NULL::BIGINT AS pob_negra_afro',
            'NULL::BIGINT AS pob_ninguno',
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
        ctefile.append(('cap', """
    SELECT geo_dep_codigo,
           SUM(TRY_CAST(cantidad AS DOUBLE)) AS capacidad_instalada
    FROM v_reps_capacidad
    WHERE geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN cap   ON gd.dep_codigo = cap.geo_dep_codigo")
        select_extra.append('cap.capacidad_instalada')
    else:
        select_extra.append('NULL::DOUBLE AS capacidad_instalada')

    # ── IPS intervenidas (Supersalud, dept-level) ────────────────────────────
    if ev.get('v_supersalud_ips_intervenidas'):
        ctefile.append(('ips_interv', """
    SELECT geo_dep_codigo, COUNT(*) AS ips_intervenidas
    FROM v_supersalud_ips_intervenidas
    WHERE geo_dep_codigo IS NOT NULL
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN ips_interv ON gd.dep_codigo = ips_interv.geo_dep_codigo")
        select_extra.append('ips_interv.ips_intervenidas')
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
        select_extra.append('eps_interv.eps_intervenidas')
    else:
        select_extra.append('NULL::BIGINT AS eps_intervenidas')

    select_extra.append('NULL::BIGINT AS eps_autorizadas')

    # ── Afiliación (aggregate latest period per mun → sum by dept) ───────────
    if ev.get('v_afiliacion'):
        ctefile.append(('afil_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_MES_CASE}) DESC
           ) AS rn
    FROM v_afiliacion
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('afil', """
    SELECT geo_dep_codigo,
           SUM(afiliados_subsidiado)                          AS afiliados_subsidiado,
           SUM(afiliados_contributivo)                        AS afiliados_contributivo,
           SUM(afiliados_total)                               AS afiliados_total,
           AVG(TRY_CAST(Cobertura AS DOUBLE)) * 100           AS cobertura_pct
    FROM afil_rn WHERE rn = 1
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN afil  ON gd.dep_codigo = afil.geo_dep_codigo")
        select_extra += [
            'afil.afiliados_subsidiado', 'afil.afiliados_contributivo', 'afil.afiliados_total',
            'afil.cobertura_pct',
        ]
    else:
        select_extra += [
            'NULL::BIGINT AS afiliados_subsidiado', 'NULL::BIGINT AS afiliados_contributivo',
            'NULL::BIGINT AS afiliados_total', 'NULL::DOUBLE AS cobertura_pct',
        ]

    # ── IRCA (AVG promedio_irca across muns, latest period per mun) ──────────
    if ev.get('v_irca'):
        ctefile.append(('irca_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_MES_CASE}) DESC
           ) AS rn
    FROM v_irca
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('irca', """
    SELECT geo_dep_codigo,
           AVG(promedio_irca) AS irca_promedio
    FROM irca_rn WHERE rn = 1
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN irca  ON gd.dep_codigo = irca.geo_dep_codigo")
        select_extra.append('irca.irca_promedio')
    else:
        select_extra.append('NULL::DOUBLE AS irca_promedio')

    # ── Mortalidad materna — dept-level rows (geo_mun_codigo IS NULL) ─────────
    if ev.get('v_ins_mortalidad_materna'):
        ctefile.append(('mm_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_dep_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_mortalidad_materna
    WHERE geo_dep_codigo IS NOT NULL AND geo_mun_codigo IS NULL"""))
        ctefile.append(('mm', f"""
    SELECT geo_dep_codigo,
           {_dd('razon_mm_actual')} AS razon_mortalidad_materna
    FROM mm_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN mm    ON gd.dep_codigo = mm.geo_dep_codigo")
        select_extra.append('mm.razon_mortalidad_materna')
    else:
        select_extra.append('NULL::DOUBLE AS razon_mortalidad_materna')

    # ── Sífilis congénita (dept-level direct join) ───────────────────────────
    # Source is the entidad territorial table (one row per dept/district).
    # casos_sc_total = NV + MF total SC cases. Incidence rate not in extracted data → NULL.
    if ev.get('v_ins_sifilis_congenita'):
        ctefile.append(('sc_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_dep_codigo
               ORDER BY
                   CASE WHEN casos_sc_total IS NOT NULL AND casos_sc_total != '' THEN 0 ELSE 1 END,
                   anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_sifilis_congenita
    WHERE geo_dep_codigo IS NOT NULL"""))
        ctefile.append(('sc', f"""
    SELECT geo_dep_codigo,
           {_di('casos_sc_total')} AS casos_sifilis_congenita,
           NULL::DOUBLE             AS incidencia_sifilis_congenita
    FROM sc_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN sc    ON gd.dep_codigo = sc.geo_dep_codigo")
        select_extra += ['sc.casos_sifilis_congenita', 'sc.incidencia_sifilis_congenita']
    else:
        select_extra += ['NULL::BIGINT AS casos_sifilis_congenita', 'NULL::DOUBLE AS incidencia_sifilis_congenita']

    # ── Desnutrición aguda (aggregate mun → dept) ────────────────────────────
    if ev.get('v_ins_desnutricion_aguda'):
        ctefile.append(('dnt_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_desnutricion_aguda
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('dnt', f"""
    SELECT geo_dep_codigo,
           SUM({_di('casos')})                  AS casos_desnutricion_aguda,
           AVG({_dd('prevalencia_por_100')})     AS prevalencia_desnutricion_aguda
    FROM dnt_rn WHERE rn = 1
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN dnt   ON gd.dep_codigo = dnt.geo_dep_codigo")
        select_extra += ['dnt.casos_desnutricion_aguda', 'dnt.prevalencia_desnutricion_aguda']
    else:
        select_extra += ['NULL::BIGINT AS casos_desnutricion_aguda', 'NULL::DOUBLE AS prevalencia_desnutricion_aguda']

    # ── Mortalidad menores 5 (dept-level) ────────────────────────────────────
    if ev.get('v_ins_mortalidad_menores5'):
        ctefile.append(('men5_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_dep_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_mortalidad_menores5
    WHERE geo_dep_codigo IS NOT NULL"""))
        ctefile.append(('men5', f"""
    SELECT geo_dep_codigo,
           {_dd('tasa_dnt')} AS tasa_mortalidad_menores5_dnt,
           {_dd('tasa_ira')} AS tasa_mortalidad_menores5_ira,
           {_dd('tasa_eda')} AS tasa_mortalidad_menores5_eda
    FROM men5_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN men5  ON gd.dep_codigo = men5.geo_dep_codigo")
        select_extra += [
            'men5.tasa_mortalidad_menores5_dnt',
            'men5.tasa_mortalidad_menores5_ira',
            'men5.tasa_mortalidad_menores5_eda',
        ]
    else:
        select_extra += [
            'NULL::DOUBLE AS tasa_mortalidad_menores5_dnt',
            'NULL::DOUBLE AS tasa_mortalidad_menores5_ira',
            'NULL::DOUBLE AS tasa_mortalidad_menores5_eda',
        ]

    # ── Dengue (dept-level) ──────────────────────────────────────────────────
    if ev.get('v_ins_dengue'):
        ctefile.append(('dengue_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_dep_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_dengue
    WHERE geo_dep_codigo IS NOT NULL"""))
        ctefile.append(('dengue', f"""
    SELECT geo_dep_codigo,
           {_dd('dengue_total')}       AS dengue_total,
           {_dd('dengue_grave_total')} AS dengue_grave_total,
           {_dd('incidencia_x100k')}   AS incidencia_dengue_x100k
    FROM dengue_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN dengue ON gd.dep_codigo = dengue.geo_dep_codigo")
        select_extra += ['dengue.dengue_total', 'dengue.dengue_grave_total', 'dengue.incidencia_dengue_x100k']
    else:
        select_extra += [
            'NULL::DOUBLE AS dengue_total', 'NULL::DOUBLE AS dengue_grave_total',
            'NULL::DOUBLE AS incidencia_dengue_x100k',
        ]

    # ── Intento suicidio (aggregate mun tasa → dept AVG) ────────────────────
    if ev.get('v_ins_intento_suicidio'):
        ctefile.append(('sui_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_mun_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_intento_suicidio
    WHERE geo_mun_codigo IS NOT NULL"""))
        ctefile.append(('sui', f"""
    SELECT geo_dep_codigo,
           AVG({_dd('tasa')}) AS tasa_intento_suicidio
    FROM sui_rn WHERE rn = 1
    GROUP BY 1"""))
        join_clauses.append("LEFT JOIN sui   ON gd.dep_codigo = sui.geo_dep_codigo")
        select_extra.append('sui.tasa_intento_suicidio')
    else:
        select_extra.append('NULL::DOUBLE AS tasa_intento_suicidio')

    # ── Violencia de género (dept-level) ─────────────────────────────────────
    if ev.get('v_ins_violencia_genero'):
        ctefile.append(('viol_rn', f"""
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY geo_dep_codigo
               ORDER BY anio DESC, ({_PE_CASE}) DESC
           ) AS rn
    FROM v_ins_violencia_genero
    WHERE geo_dep_codigo IS NOT NULL"""))
        ctefile.append(('viol', f"""
    SELECT geo_dep_codigo,
           {_dd('violencia_fisica')}              AS violencia_fisica,
           {_dd('violencia_psicologica')}         AS violencia_psicologica,
           {_dd('negligencia_abandono')}          AS negligencia_abandono,
           {_dd('violencia_sexual')}              AS violencia_sexual,
           {_dd('violencia_genero_intrafamiliar')} AS violencia_genero_intrafamiliar
    FROM viol_rn WHERE rn = 1"""))
        join_clauses.append("LEFT JOIN viol  ON gd.dep_codigo = viol.geo_dep_codigo")
        select_extra += [
            'viol.violencia_fisica', 'viol.violencia_psicologica', 'viol.negligencia_abandono',
            'viol.violencia_sexual', 'viol.violencia_genero_intrafamiliar',
        ]
    else:
        select_extra += [
            'NULL::DOUBLE AS violencia_fisica', 'NULL::DOUBLE AS violencia_psicologica',
            'NULL::DOUBLE AS negligencia_abandono', 'NULL::DOUBLE AS violencia_sexual',
            'NULL::DOUBLE AS violencia_genero_intrafamiliar',
        ]

    select_extra += [
        'NULL::DOUBLE  AS lsp',
        'NULL::DOUBLE  AS vsp',
        'NULL::VARCHAR AS gestion_riesgo',
    ]

    ctes_sql = ',\n'.join(f"{name} AS ({body}" + "\n)" for name, body in ctefile)
    joins_sql = '\n'.join(join_clauses)
    select_sql = ',\n    '.join(select_extra)

    sql = f"""CREATE OR REPLACE VIEW v_metricas_departamento AS
WITH
{ctes_sql}
SELECT
    gd.dep_codigo  AS geo_dep_codigo,
    gd.dep_dane    AS departamento,
    {select_sql}
FROM geo_dep gd
{joins_sql}
"""
    con.execute(sql)
    n = con.execute("SELECT COUNT(*) FROM v_metricas_departamento").fetchone()[0]
    print(f'  v_metricas_departamento: {n:,} departamentos')


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
            print('metricas: ADVERTENCIA — geo_maestro no existe. Ejecuta transform.py primero.')
            return

        ev = {n: n in existing for n in [
            'v_demografico_edad_sexo', 'v_demografico_etnico',
            'v_reps_prestadores', 'v_reps_capacidad',
            'v_afiliacion', 'v_irca',
            'v_ins_mortalidad_materna', 'v_ins_sifilis_congenita',
            'v_ins_desnutricion_aguda', 'v_ins_intento_suicidio',
            'v_ins_mortalidad_menores5', 'v_ins_dengue', 'v_ins_violencia_genero',
            'v_supersalud_ips_intervenidas', 'v_supersalud_eps_intervenidas',
        ]}
        missing = [k for k, v in ev.items() if not v]
        if missing:
            log.info(f'metricas: vistas no disponibles (serán NULL): {missing}')

        _build_municipio_view(con, ev)
        _build_departamento_view(con, ev)
        print('metricas OK — vistas v_metricas_municipio y v_metricas_departamento creadas')
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
