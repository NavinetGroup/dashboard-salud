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
    'bdua':        'MSPS — BDUA / cifras de afiliación',
    'reps':        'MSPS — REPS',
    'supersalud':  'Supersalud — entidades en medida especial',
    'sivicap':     'INS — SIVICAP',
    'sivigila':    'INS — SIVIGILA (boletines por periodo epidemiológico)',
    'cuipo':       'CGR — CUIPO / MSPS',
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
SALUD_PUBLICA = [
    Indicator('mm', 'Razón de mortalidad materna', 'razon_mortalidad_materna',
              'por 100.000 nacidos vivos', 1, 'pregnant_woman', True, source='sivigila',
              period_col='periodo_mortalidad_materna'),
    Indicator('sifilis', 'Sífilis congénita', 'casos_sifilis_congenita', 'casos', 0,
              'child_care', True, 'abs', source='sivigila', period_col='periodo_sifilis', dept_only=True),
    Indicator('dnt', 'Prevalencia de desnutrición aguda en menores de 5 años',
              'prevalencia_desnutricion_aguda', '%', 2, 'child_friendly', True, 'pp',
              source='sivigila', period_col='periodo_desnutricion'),
    Indicator('mort_dnt', 'Tasa de mortalidad en menores de 5 años por desnutrición',
              'tasa_mortalidad_menores5_dnt', 'por 100.000 menores de 5 años', 2,
              'footprint', True, source='sivigila', period_col='periodo_menores5', dept_only=True),
    Indicator('irca', 'Índice de riesgo de la calidad del agua (IRCA)', 'irca_promedio',
              'puntos (0–100)', 1, 'water_drop', True, source='sivicap', period_col='irca_periodo'),
    Indicator('dengue_grave', 'Incidencia de dengue grave', 'incidencia_dengue_grave_x100k',
              'por 100.000 hab.', 2, 'pest_control', True, source='sivigila',
              period_col='periodo_dengue', dept_only=True),
    Indicator('suicidio', 'Tasa de incidencia de intento de suicidio', 'tasa_intento_suicidio',
              'por 100.000 hab.', 1, 'volunteer_activism', True, source='sivigila',
              period_col='periodo_suicidio'),
    Indicator('violencia', 'Violencia de género e intrafamiliar (violencia física)',
              'violencia_fisica', 'por 100.000 hab.', 1, 'front_hand', True, source='sivigila',
              period_col='periodo_violencia', dept_only=True),
    Indicator('lsp', 'Cumplimiento de estándares de calidad de los LSP', None, '%',
              icon='biotech', trend='', pending='No publicado: INS Dirección de Redes. Solicitar vía Supersalud.'),
    Indicator('vsp', 'Cumplimiento de indicadores de gestión en VSP', None, '%',
              icon='monitoring', trend='', pending='INS — informe trimestral de evaluación del desempeño (por integrar).'),
    Indicator('capacidades', 'Capacidades básicas en gestión del riesgo', None, 'puntaje 0–5',
              icon='shield_person', trend='', pending='INS — tablero de capacidades básicas (por integrar).'),
]

# ── Aseguramiento ─────────────────────────────────────────────────────────────
ASEGURAMIENTO = [
    Indicator('eps_total', 'Total EPS autorizadas', None, 'EPS', icon='apartment', trend='',
              pending='BDUA por municipio (datos.gov.co, por integrar).'),
    Indicator('eps_contrib', 'EPS régimen contributivo', None, 'EPS', icon='groups', trend='',
              pending='BDUA por municipio (datos.gov.co, por integrar).'),
    Indicator('eps_subs', 'EPS régimen subsidiado', None, 'EPS', icon='diversity_1', trend='',
              pending='BDUA por municipio (datos.gov.co, por integrar).'),
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

# ── Financiamiento (11) — CUIPO / SICODIS / ADRES por integrar; 9–11 del cliente ─
_FIN_PENDING = 'CUIPO (CGR) / SICODIS — por integrar.'
_CLIENT = 'Dato interno: solicitar a Supersalud / MSPS.'
FINANCIAMIENTO = [
    Indicator('fin1', 'Ejecución presupuestal — compromisos vs. ingresos FLS', None, '%',
              icon='request_quote', trend='', pending=_FIN_PENDING),
    Indicator('fin2', 'Ejecución presupuestal — compromisos FLS', None, '%',
              icon='receipt_long', trend='', pending=_FIN_PENDING),
    Indicator('fin3', 'Ejecución presupuestal — pagos vs. ingresos', None, '%',
              icon='currency_exchange', trend='', pending=_FIN_PENDING),
    Indicator('fin4', 'SGP salud pública — compromisos', None, '%', icon='ecg_heart',
              trend='', pending=_FIN_PENDING),
    Indicator('fin5', 'SGP salud pública — pagos', None, '%', icon='volunteer_activism',
              trend='', pending=_FIN_PENDING),
    Indicator('fin6', 'SGP subsidio a la oferta — compromisos', None, '%', icon='local_hospital',
              trend='', pending=_FIN_PENDING),
    Indicator('fin7', 'SGP subsidio a la oferta — giros', None, '%', icon='sync_alt',
              trend='', pending='SICODIS + giros MSPS (parcial); confirmar con el cliente.'),
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
