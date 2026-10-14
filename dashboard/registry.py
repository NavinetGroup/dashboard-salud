# -*- coding: utf-8 -*-
"""Indicator registry for the FCT design (docs/reference/DASHBOARD_FCT.docx).

One entry per indicator card: what to show, how to format it, which way is
"better" for the trend arrow, and where it comes from. Pages and the Ficha
summary are built from this list, so labels, units and sources live in one
place. Indicators without data yet are listed too (status 'pendiente'), so the
layout matches the client's design and says what is outstanding.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    col: str | None            # column in metricas_* (None = no data yet)
    unit: str = ''
    decimals: int = 0
    icon: str = 'insights'     # Material Symbols name (rendered by Streamlit)
    lower_is_better: bool | None = None   # None = no good/bad direction
    trend: str = 'pct'         # 'pct' relative · 'pp' percentage points · 'abs' count difference · '' none
    source: str = ''
    period_col: str | None = None
    dept_only: bool = False    # no municipal value (INS entity tables)
    pending: str = ''          # why it is missing and where it will come from
    # (col, period_col, note): shown when `col` has no value for the selection,
    # e.g. the INS PDF bulletin while the year's SIVIGILA microdata aren't out yet
    fallback: tuple | None = None


# ── Módulos (order and colours from the mockups) ─────────────────────────────
MODULES = {
    'ficha':          ('Ficha de caracterización territorial', '#0B5D5E', 'assignment'),
    'demograficos':   ('Demográficos',             '#26A69A', 'groups'),
    'salud_publica':  ('Salud pública',            '#7E57C2', 'ecg_heart'),
    'aseguramiento':  ('Aseguramiento',            '#1E88E5', 'verified_user'),
    'prestacion':     ('Prestación de servicios',  '#43A047', 'local_hospital'),
    'financiamiento': ('Financiamiento',           '#F57C00', 'payments'),
}

SRC = {
    'dane':        'DANE — Proyecciones de población',
    'bdua':        'ADRES / MSPS — BDUA (datos.gov.co) y cifras de afiliación MSPS',
    'reps':        'MSPS — REPS',
    'supersalud':  'Supersalud — entidades en medida especial',
    'sivicap':     'INS — SIVICAP',
    'sivigila':    'INS — SIVIGILA (microdatos anuales; boletín PDF para el año en curso)',
    'cuipo':       'CGR — CUIPO (ejecución presupuestal, datos.gov.co)',
    'sicodis':     'DNP — SICODIS (asignaciones SGP)',
    'cuipo_sgp':   'CGR — CUIPO · DNP — SICODIS',
}

# ── Demográficos ──────────────────────────────────────────────────────────────
DEMOGRAFICOS = [
    Indicator('pob_hombres', 'Total hombres', 'pob_hombres', 'hab.', icon='man', source='dane'),
    Indicator('pob_mujeres', 'Total mujeres', 'pob_mujeres', 'hab.', icon='woman', source='dane'),
    Indicator('pob_total', 'Total población', 'pob_total', 'hab.', icon='groups', source='dane'),
    Indicator('pob_etnica', 'Población con pertenencia étnico-racial', 'pob_con_pertenencia',
              'personas', icon='diversity_3', source='dane'),
]

ETNIAS = [   # (column, label, colour) — colours from the mockup
    ('pob_indigena',    'Indígena',                                          '#1565C0'),
    ('pob_gitana_rrom', 'Gitana o Rrom',                                     '#7CB342'),
    ('pob_raizal',      'Raizal',                                            '#FBC02D'),
    ('pob_palenquera',  'Palenquera de San Basilio',                         '#FB8C00'),
    ('pob_negra_afro',  'Negra, mulata, afrodescendiente o afrocolombiana',  '#7E57C2'),
    ('pob_ninguno',     'Ningún grupo étnico-racial',                        '#B0BEC5'),
]

# ── Salud pública (11) ────────────────────────────────────────────────────────
# Cards read the SIVIGILA microdata (final, all municipalities). For a year whose
# microdata aren't published yet (the current year), they fall back to the INS
# PDF bulletin and say so.
_PDF_NOTE = 'Boletín INS (preliminar): microdatos SIVIGILA aún no publicados para este año'
_PDF_NOTE_LISTED = _PDF_NOTE + '; solo municipios listados en el boletín'
SALUD_PUBLICA = [
    Indicator('mm', 'Razón de mortalidad materna', 'razon_mortalidad_materna',
              'por 100.000 nacidos vivos', 1, 'pregnant_woman', True, source='sivigila',
              period_col='periodo_mortalidad_materna'),
    Indicator('sifilis', 'Sífilis congénita', 'sv_sifilis_casos', 'casos', 0,
              'child_care', True, 'abs', source='sivigila', period_col='periodo_sivigila',
              fallback=('casos_sifilis_congenita', 'periodo_sifilis', _PDF_NOTE)),
    Indicator('dnt', 'Prevalencia de desnutrición aguda en menores de 5 años',
              'sv_desnutricion_tasa', '%', 2, 'child_friendly', True, 'pp',
              source='sivigila', period_col='periodo_sivigila',
              fallback=('prevalencia_desnutricion_aguda', 'periodo_desnutricion', _PDF_NOTE_LISTED)),
    Indicator('mort_dnt', 'Tasa de mortalidad en menores de 5 años por desnutrición',
              'sv_mort_desnutricion_tasa', 'por 100.000 menores de 5 años', 2,
              'footprint', True, source='sivigila', period_col='periodo_sivigila',
              fallback=('tasa_mortalidad_menores5_dnt', 'periodo_menores5', _PDF_NOTE)),
    Indicator('irca', 'Índice de riesgo de la calidad del agua (IRCA)', 'irca_promedio',
              'puntos (0–100)', 1, 'water_drop', True, source='sivicap', period_col='irca_periodo'),
    Indicator('dengue_grave', 'Incidencia de dengue grave', 'sv_dengue_grave_tasa',
              'por 100.000 hab.', 2, 'pest_control', True, source='sivigila',
              period_col='periodo_sivigila'),
    Indicator('suicidio', 'Tasa de incidencia de intento de suicidio', 'sv_suicidio_tasa',
              'por 100.000 hab.', 1, 'volunteer_activism', True, source='sivigila',
              period_col='periodo_sivigila',
              fallback=('tasa_intento_suicidio', 'periodo_suicidio', _PDF_NOTE_LISTED)),
    Indicator('violencia', 'Tasa de notificación de violencia de género e intrafamiliar',
              'sv_violencia_tasa', 'por 100.000 hab.', 1, 'front_hand', True, source='sivigila',
              period_col='periodo_sivigila',
              fallback=('violencia_fisica', 'periodo_violencia',
                        'Boletín INS (preliminar): solo violencia física, nivel departamental')),
    Indicator('lsp', 'Cumplimiento de estándares de calidad de los LSP', None, '%',
              icon='biotech', trend='', pending='No publicado: INS Dirección de Redes. Solicitar vía Supersalud.'),
    Indicator('vsp', 'Cumplimiento de indicadores de gestión en VSP', None, '%',
              icon='monitoring', trend='', pending='INS — informe trimestral de evaluación del desempeño (por integrar).'),
    Indicator('capacidades', 'Capacidades básicas en gestión del riesgo', None, 'puntaje 0–5',
              icon='shield_person', trend='', pending='INS — tablero de capacidades básicas (por integrar).'),
]

# ── Aseguramiento ─────────────────────────────────────────────────────────────
ASEGURAMIENTO = [
    # BDUA lists the EPS with affiliates in each territory; the authorisation per
    # territory is not published, so the cards say "con afiliados".
    Indicator('eps_total', 'Total EPS con afiliados', 'eps_total', 'EPS', icon='apartment',
              trend='', source='bdua', period_col='eps_fecha_corte'),
    Indicator('eps_contrib', 'EPS régimen contributivo', 'eps_contributivo', 'EPS', icon='groups',
              trend='', source='bdua', period_col='eps_fecha_corte'),
    Indicator('eps_subs', 'EPS régimen subsidiado', 'eps_subsidiado', 'EPS', icon='diversity_1',
              trend='', source='bdua', period_col='eps_fecha_corte'),
    Indicator('eps_interv', 'EPS intervenidas', 'eps_intervenidas', 'EPS', icon='policy',
              trend='', source='supersalud', dept_only=True),
    Indicator('afil_subs', 'Población afiliada régimen subsidiado', 'afiliados_subsidiado',
              'afiliados', icon='family_restroom', source='bdua', period_col='periodo_afiliacion'),
    Indicator('afil_contrib', 'Población afiliada régimen contributivo', 'afiliados_contributivo',
              'afiliados', icon='badge', source='bdua', period_col='periodo_afiliacion'),
    Indicator('cobertura', 'Cobertura de afiliación', 'cobertura_pct', '%', 1, 'shield',
              False, 'pp', source='bdua', period_col='periodo_afiliacion'),
]

SISBEN = [   # share of afiliados_subsidiado (FCT Aseguramiento 8–11)
    Indicator('sin_sisben', 'Afiliados al régimen subsidiado sin Sisbén IV', 'afil_sin_sisben',
              'afiliados', icon='badge', lower_is_better=True, source='bdua', period_col='periodo_afiliacion'),
    Indicator('esp_sin_sisben', 'Afiliados poblaciones especiales sin Sisbén IV',
              'afil_especiales_sin_sisben', 'afiliados', icon='accessible', lower_is_better=True,
              source='bdua', period_col='periodo_afiliacion'),
    Indicator('oficio_sin_sisben', 'Afiliados de oficio sin Sisbén IV', 'afil_oficio_sin_sisben',
              'afiliados', icon='assignment_turned_in', lower_is_better=True, source='bdua', period_col='periodo_afiliacion'),
    Indicator('no_pobre', 'Afiliados régimen subsidiado no pobre no vulnerable',
              'afil_no_pobre_no_vulnerable', 'afiliados', icon='group_remove',
              lower_is_better=True, source='bdua', period_col='periodo_afiliacion'),
]

# ── Prestación de servicios ───────────────────────────────────────────────────
PRESTACION = [
    Indicator('ips_total', 'Total IPS', 'ips_total', 'IPS habilitadas', icon='local_hospital',
              trend='', source='reps'),
    Indicator('ips_publica', 'IPS públicas', 'ips_publica', 'IPS', icon='account_balance',
              trend='', source='reps'),
    Indicator('ips_privada', 'IPS privadas', 'ips_privada', 'IPS', icon='domain', trend='', source='reps'),
    Indicator('ips_mixta', 'IPS mixtas', 'ips_mixta', 'IPS', icon='corporate_fare', trend='', source='reps'),
]

CAPACIDAD = [
    Indicator('camas', 'Camas hospitalarias', 'camas', 'camas', icon='bed', trend='', source='reps'),
    Indicator('consultorios', 'Consultorios', 'consultorios', '', icon='stethoscope', trend='', source='reps'),
    Indicator('salas', 'Salas de cirugía', 'salas_cirugia', '', icon='surgical', trend='', source='reps'),
    Indicator('uci_ad', 'UCI adultos', 'uci_adultos', 'camas', icon='monitor_heart', trend='', source='reps'),
    Indicator('uci_ped', 'UCI pediátricas', 'uci_pediatricas', 'camas', icon='child_care', trend='', source='reps'),
]

# ── Financiamiento (11) — 1–7 CUIPO (CGR) + SICODIS (DNP); 8 por integrar; 9–11 del cliente ─
# Formulas are a proposal pending Supersalud validation: docs/FINANCIAMIENTO_FORMULAS.md.
# CUIPO is year-to-date, so values rise through the year; the trend compares the
# same quarter a year earlier (percentage points).
_CLIENT = 'Dato interno: solicitar a Supersalud / MSPS.'


def _fin(key, label, col, icon, source='cuipo', better=False):
    return Indicator(key, label, col, '%', decimals=1, icon=icon, trend='pp', source=source,
                     period_col='periodo_cuipo', lower_is_better=None if better is None else not better)


FINANCIAMIENTO = [
    # compromisos > recaudo is not "good" or "bad" by itself (commitments run ahead of cash)
    _fin('fin1', 'Ejecución presupuestal — compromisos vs. ingresos FLS', 'fin_comp_recaudo',
         'request_quote', better=None),
    _fin('fin2', 'Ejecución presupuestal — compromisos FLS', 'fin_comp_aprop', 'receipt_long'),
    _fin('fin3', 'Ejecución presupuestal — pagos vs. ingresos', 'fin_pagos_recaudo', 'currency_exchange'),
    _fin('fin4', 'SGP salud pública — compromisos', 'fin_sgp_sp_comp', 'ecg_heart', 'cuipo_sgp'),
    _fin('fin5', 'SGP salud pública — pagos', 'fin_sgp_sp_pagos', 'volunteer_activism', 'cuipo_sgp'),
    _fin('fin6', 'SGP subsidio a la oferta — compromisos', 'fin_sgp_of_comp', 'local_hospital', 'cuipo_sgp'),
    _fin('fin7', 'SGP subsidio a la oferta — giros', 'fin_sgp_of_giros', 'sync_alt', 'cuipo_sgp'),
    Indicator('fin8', 'Cumplimiento meta de cofinanciación régimen subsidiado', None, '%',
              icon='target', trend='', pending='Matriz de continuidad MSPS + ADRES LMA — por integrar.'),
    Indicator('fin9', 'Deuda Circular 030 de 2013 (pagos / compromisos firmados)', None, '%',
              icon='description', trend='', pending=_CLIENT),
    Indicator('fin10', 'Pagos por prestación de servicios PNA y NPBS', None, '%',
              icon='medical_services', trend='', pending=_CLIENT),
    Indicator('fin11', 'Pagos realizados a migrantes no regulares', None, '%',
              icon='public', trend='', pending=_CLIENT),
]

# ── Ficha: the KPIs shown per module band ────────────────────────────────────
_BY_KEY = {i.key: i for group in (DEMOGRAFICOS, SALUD_PUBLICA, ASEGURAMIENTO, SISBEN,
                                   PRESTACION, CAPACIDAD, FINANCIAMIENTO) for i in group}

FICHA = {
    'demograficos':   ['pob_hombres', 'pob_mujeres', 'pob_total', 'pob_etnica'],
    'salud_publica':  ['mm', 'dnt', 'mort_dnt', 'suicidio'],
    'aseguramiento':  ['eps_total', 'eps_interv', 'afil_subs', 'afil_contrib', 'cobertura'],
    'prestacion':     ['ips_total', 'ips_publica', 'ips_privada', 'ips_mixta', 'camas'],
    'financiamiento': ['fin1', 'fin4', 'fin6', 'fin8'],
}


def get(key: str) -> Indicator:
    return _BY_KEY[key]
