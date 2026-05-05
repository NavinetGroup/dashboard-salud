# -*- coding: utf-8 -*-
"""Informe Regional de Salud — Colombia."""

import math
from pathlib import Path

import pandas as pd
import streamlit as st

from data import (
    get_available_months, get_available_years,
    get_dept_metrics, get_dift18_dept, get_dift18_dist, get_dift18_mun,
    get_mun_metrics, get_source_periods, load_geojson,
)
from charts import (
    bar_comparison, bar_dift18_scores, bar_ethnic, bar_muns_top,
    bar_violence, choropleth_dept, donut_afil, donut_gender, donut_ips,
    gauge_irca, gauge_pct,
)

st.set_page_config(page_title='Informe Regional de Salud', layout='wide',
                   initial_sidebar_state='expanded')

_LOGO_PATH = Path(__file__).parent / 'Logo-Supersalud-2024.svg'

_SRC = {
    'demografia':          ('DANE',          'Proyecciones de poblacion PPED 2018-2050'),
    'aseguramiento':       ('MSPS / BDUA',   'Base de Datos Unica de Afiliados'),
    'reps':                ('MSPS / REPS',   'Registro Especial de Prestadores'),
    'irca':                ('INS / SIVICAP', 'Indice de Riesgo Calidad del Agua'),
    'mortalidad_materna':  ('INS / SIVIGILA','Informe evento mortalidad materna'),
    'sifilis_congenita':   ('INS / SIVIGILA','Informe evento sifilis congenita'),
    'desnutricion_aguda':  ('INS / SIVIGILA','Informe evento desnutricion aguda'),
    'mortalidad_menores5': ('INS / SIVIGILA','Informe evento mortalidad menores de 5 anos'),
    'dengue':              ('INS / SIVIGILA','Informe evento dengue'),
    'intento_suicidio':    ('INS / SIVIGILA','Informe evento intento de suicidio'),
    'violencia_genero':    ('INS / SIVIGILA','Informe evento violencia de genero e intrafamiliar'),
    'dift18':              ('MSPS',           'DIFT18 Tablero de control Desempeno ET 2024'),
}

# Source URLs — used by _src() to add a clickable link
_URLS: dict[str, str] = {
    'demografia':          'https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion',
    'aseguramiento':       'https://www.minsalud.gov.co/proteccionsocial/Regimensubsidiado/Paginas/base-de-datos-unica-de-afiliados.aspx',
    'reps':                'https://prestadores.minsalud.gov.co/habilitacion/',
    'irca':                'https://sivicap.ins.gov.co/',
    'mortalidad_materna':  'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'sifilis_congenita':   'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'desnutricion_aguda':  'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'mortalidad_menores5': 'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'dengue':              'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'intento_suicidio':    'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'violencia_genero':    'https://www.ins.gov.co/buscador-eventos/SitePages/boletines.aspx',
    'dift18':              'https://www.minsalud.gov.co/',
}

# ── Colours ──────────────────────────────────────────────────────────────────
_C_PRIMARY   = '#1565C0'
_C_SECONDARY = '#0288D1'
_C_SUCCESS   = '#2E7D32'
_C_WARNING   = '#F57F17'
_C_DANGER    = '#C62828'
_C_NEUTRAL   = '#546E7A'

# ── Shared CSS injected once ──────────────────────────────────────────────────
st.markdown("""
<style>
/* Section headers */
.sec-header {
    font-size: 1.25rem; font-weight: 700; color: #1A237E;
    padding: 6px 0 2px 0; margin-top: 8px;
}
/* KPI card */
.kpi-card {
    background: white; border-radius: 14px;
    padding: 20px 18px 16px 18px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.07);
    text-align: center; height: 120px;
    display: flex; flex-direction: column; justify-content: center;
}
.kpi-label { font-size: 11px; font-weight: 600; color: #90A4AE;
             text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; }
.kpi-value { font-size: 26px; font-weight: 800; line-height: 1.1; }
.kpi-sub   { font-size: 11px; color: #90A4AE; margin-top: 4px; }
/* Metric panel card */
.mp-card {
    border-radius: 10px; padding: 12px 16px; margin: 5px 0;
    box-shadow: 0 1px 6px rgba(0,0,0,0.07);
}
.mp-label { font-size: 11px; font-weight: 600; letter-spacing: 0.4px;
            text-transform: uppercase; margin-bottom: 3px; }
.mp-value { font-size: 22px; font-weight: 800; line-height: 1.2; }
.mp-unit  { font-size: 12px; opacity: 0.7; font-weight: 400; margin-left: 3px; }
/* Source caption */
.src-line { font-size: 11px; color: #90A4AE; margin: -6px 0 10px 0; }
/* N/D placeholder */
.nd-value { color: #B0BEC5; font-size: 16px; font-weight: 400; }
/* Anchor offset so sticky header doesn't cover target */
.scroll-anchor { display: block; height: 0; visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _v(row: pd.Series, col: str):
    v = row.get(col)
    return None if v is None or pd.isna(v) else v


def _fmt(val, dec: int = 0) -> str:
    if val is None or pd.isna(val):
        return 'N/D'
    if isinstance(val, float):
        return f'{val:,.{dec}f}'
    return f'{int(val):,}'


def _nat_avg(df_dept: pd.DataFrame, col: str):
    s = pd.to_numeric(df_dept[col], errors='coerce')
    return s.mean() if s.notna().any() else None


def _kpi_card(label: str, value: str, subtitle: str = '', color: str = _C_PRIMARY) -> str:
    return f"""
<div class="kpi-card" style="border-top: 4px solid {color}">
  <div class="kpi-label">{label}</div>
  <div class="kpi-value" style="color:{color}">{value}</div>
  <div class="kpi-sub">{subtitle}</div>
</div>"""


def _mp(label: str, value: str, unit: str = '',
        highlight: bool = False, color: str = _C_PRIMARY) -> str:
    """Single metric panel card."""
    if highlight:
        bg, label_c, val_c, unit_c = color, 'rgba(255,255,255,0.75)', 'white', 'rgba(255,255,255,0.6)'
    else:
        bg, label_c, val_c, unit_c = '#F8FAFC', '#90A4AE', '#1A237E', '#90A4AE'
    if value == 'N/D':
        val_html = '<span class="nd-value">N/D</span>'
    else:
        val_html = f'{value}<span class="mp-unit" style="color:{unit_c}">{unit}</span>'
    return f"""
<div class="mp-card" style="background:{bg}">
  <div class="mp-label" style="color:{label_c}">{label}</div>
  <div class="mp-value" style="color:{val_c}">{val_html}</div>
</div>"""


def _panel(items: list[tuple], title: str = '') -> None:
    """Render a stacked set of metric cards.
    items: [(label, value, unit, highlight)]
    """
    title_html = f'<div style="font-size:12px;font-weight:700;color:#546E7A;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">{title}</div>' if title else ''
    cards = ''.join(_mp(l, v, u, h) for l, v, u, h in items)
    st.markdown(f'<div>{title_html}{cards}</div>', unsafe_allow_html=True)


def _section(title: str, description: str = '', anchor: str = '') -> None:
    if anchor:
        st.markdown(f'<a class="scroll-anchor" id="{anchor}"></a>', unsafe_allow_html=True)
    st.markdown(f'<div class="sec-header">{title}</div>', unsafe_allow_html=True)
    if description:
        st.caption(description)
    st.divider()


def _src(key: str, periods: dict) -> None:
    inst, report = _SRC.get(key, ('', ''))
    period = periods.get(key, '')
    url = _URLS.get(key, '')
    link = f' <a href="{url}" target="_blank" style="color:#90A4AE;font-size:10px">&#x1F517;</a>' if url else ''
    st.markdown(
        f'<div class="src-line">Fuente: <b>{inst}</b> &mdash; {report}{link}'
        f'{"&nbsp;&nbsp;|&nbsp;&nbsp;Ultimo dato: <b>" + period + "</b>" if period else ""}</div>',
        unsafe_allow_html=True,
    )


def _cmp_bar(entity_label, entity_val, dept_label, dept_val, nat_val,
             unit='', title=''):
    if entity_label == dept_label:
        labels = ['Nacional (prom.)', dept_label]
        values = [nat_val, dept_val]
        idx = 1
    else:
        labels = ['Nacional (prom.)', dept_label, entity_label]
        values = [nat_val, dept_val, entity_val]
        idx = 2
    return bar_comparison(labels, values, unit=unit, title=title, entity_idx=idx)


def _dift_badge(pts_val) -> str:
    if pts_val is None:
        return ''
    pts = max(1, min(4, round(float(pts_val))))
    _colors = {1: '#EF5350', 2: '#FFA726', 3: '#66BB6A', 4: '#26A69A'}
    _labels = {1: 'Bajo', 2: 'En proceso', 3: 'Satisfactorio', 4: 'Optimo'}
    c = _colors[pts]
    return (f'<div style="display:inline-block;background:{c};color:white;border-radius:8px;'
            f'padding:4px 10px;font-size:12px;font-weight:700;margin-top:6px">'
            f'DIFT18: {pts}/4 — {_labels[pts]}</div>')


# ── Sidebar ───────────────────────────────────────────────────────────────────

if _LOGO_PATH.exists():
    st.sidebar.image(str(_LOGO_PATH), width=170)
else:
    st.sidebar.markdown('**Supersalud**')

st.sidebar.title('Informe Regional')
st.sidebar.caption('Ministerio de Salud — Colombia')
st.sidebar.divider()

# Period selectors
available_years = get_available_years()
if available_years:
    sel_year = st.sidebar.selectbox('Ano de referencia', available_years, index=0)
    month_opts = ['Ultimo disponible'] + get_available_months(sel_year)
    sel_month_opt = st.sidebar.selectbox('Mes de referencia', month_opts, index=0)
    filter_month = None if sel_month_opt == 'Ultimo disponible' else sel_month_opt
else:
    sel_year = None
    filter_month = None

st.sidebar.divider()

# Entity selectors
df_dept_all = get_dept_metrics(year=sel_year, month=filter_month)
geojson     = load_geojson()
periods     = get_source_periods()
dept_list   = df_dept_all['departamento'].dropna().tolist()

sel_dept = st.sidebar.selectbox(
    'Departamento', dept_list,
    index=0,
)
dept_row  = df_dept_all[df_dept_all['departamento'] == sel_dept].iloc[0]
dept_code = int(dept_row['geo_dep_codigo'])

df_mun_all = get_mun_metrics(dept_code, year=sel_year, month=filter_month)
use_mun  = st.sidebar.checkbox('Desglosar por municipio', value=False)
sel_mun  = None
mun_row  = None
mun_code = None
if use_mun:
    _mun_list = df_mun_all['municipio'].dropna().tolist()
    if _mun_list:
        sel_mun = st.sidebar.selectbox('Municipio', _mun_list)
        mun_row  = df_mun_all[df_mun_all['municipio'] == sel_mun].iloc[0]
        mun_code = int(mun_row['geo_mun_codigo']) if pd.notna(mun_row.get('geo_mun_codigo')) else None
    else:
        st.sidebar.caption('Sin municipios disponibles')
        use_mun = False

entity_row   = mun_row if use_mun else dept_row
entity_label = sel_mun if use_mun else sel_dept
dept_label   = sel_dept

dift_is_district = False
if use_mun and mun_code:
    dift_ent = get_dift18_dist(mun_code)
    if dift_ent is not None:
        dift_is_district = True
    else:
        dift_ent = get_dift18_mun(mun_code)
else:
    dift_ent = get_dift18_dept(dept_code)

period_label = f'{sel_month_opt.title()} {sel_year}' if sel_year else 'Ultimo disponible'
st.sidebar.divider()
st.sidebar.caption(f'Periodo: **{period_label}**')
st.sidebar.caption('DANE · REPS · IRCA · INS · Supersalud · DIFT18')
st.sidebar.divider()
st.sidebar.markdown(
    '**Ir a sección**\n'
    '- [Contexto geográfico](#geo)\n'
    '- [Demografía](#demografia)\n'
    '- [Aseguramiento](#aseguramiento)\n'
    '- [Infraestructura](#infraestructura)\n'
    '- [Calidad del agua](#irca)\n'
    '- [Mortalidad materna](#mortalidad-materna)\n'
    '- [Sífilis congénita](#sifilis)\n'
    '- [Desnutrición aguda](#desnutricion)\n'
    '- [Mortalidad <5 años](#menores5)\n'
    '- [Dengue](#dengue)\n'
    '- [Salud mental](#suicidio)\n'
    '- [Violencia](#violencia)\n'
    '- [Desempeño ET](#dift18)\n'
    '- [Tabla consolidada](#tabla)\n'
)


# ── Page header ───────────────────────────────────────────────────────────────

subtitle = f'{sel_mun} — {sel_dept}' if use_mun else sel_dept
st.title(f'Informe de Salud: {subtitle}')
st.caption(f'Periodo de referencia: {period_label}  |  Fuentes: MSPS, INS, DANE, Supersalud')

# KPI cards row
cob   = _v(entity_row, 'cobertura_pct')
irca  = _v(entity_row, 'irca_promedio')
irca_risk = entity_row.get('irca_nivel_riesgo', '') or ''

c1, c2, c3, c4 = st.columns(4)
c1.markdown(_kpi_card('Poblacion', _fmt(_v(entity_row, 'pob_total')),
                       color=_C_PRIMARY), unsafe_allow_html=True)
c2.markdown(_kpi_card('IPS habilitadas', _fmt(_v(entity_row, 'ips_total')),
                       color=_C_SECONDARY), unsafe_allow_html=True)
c3.markdown(_kpi_card('Cobertura', f'{cob:.1f}%' if cob else 'N/D',
                       color=_C_SUCCESS if cob and cob >= 90 else _C_WARNING),
            unsafe_allow_html=True)
c4.markdown(_kpi_card('IRCA promedio', f'{_fmt(irca, 1)} pts', irca_risk,
                       color=_C_SUCCESS if irca and irca <= 14 else
                             _C_WARNING if irca and irca <= 35 else _C_DANGER),
            unsafe_allow_html=True)
st.markdown('<div style="margin-bottom:20px"></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONTEXTO GEOGRAFICO
# ══════════════════════════════════════════════════════════════════════════════
_section('Contexto geografico',
         'Posicion del departamento en el panorama nacional de salud.',
         anchor='geo')
_src('demografia', periods)

col_chart, col_data = st.columns([3, 2])
with col_chart:
    fig_map = choropleth_dept(
        df_dept_all[['departamento', 'dep_str', 'pob_total']].dropna(subset=['pob_total']),
        'pob_total', geojson, 'Poblacion total', '',
    )
    st.plotly_chart(fig_map, use_container_width=True)

with col_data:
    st.markdown('**Ranking departamental**')
    top = (df_dept_all[['departamento', 'pob_total', 'ips_total',
                         'afiliados_total', 'irca_promedio']]
           .sort_values('pob_total', ascending=False)
           .reset_index(drop=True))
    st.dataframe(
        top, use_container_width=True, height=430,
        column_config={
            'departamento':   'Departamento',
            'pob_total':      st.column_config.NumberColumn('Poblacion',  format='%,.0f'),
            'ips_total':      st.column_config.NumberColumn('IPS',        format='%,.0f'),
            'afiliados_total':st.column_config.NumberColumn('Afiliados',  format='%,.0f'),
            'irca_promedio':  st.column_config.NumberColumn('IRCA',       format='%.1f'),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. DEMOGRAFIA
# ══════════════════════════════════════════════════════════════════════════════
_section('Demografia', 'Composicion poblacional por sexo y pertenencia etnica.',
         anchor='demografia')
_src('demografia', periods)

col_chart, col_data = st.columns([3, 2])
with col_chart:
    c_g, c_e = st.columns(2)
    with c_g:
        st.plotly_chart(donut_gender(entity_row), use_container_width=True)
    with c_e:
        st.plotly_chart(bar_ethnic(entity_row), use_container_width=True)

with col_data:
    pob_h = _v(entity_row, 'pob_hombres')
    pob_m = _v(entity_row, 'pob_mujeres')
    pob_t = _v(entity_row, 'pob_total')
    _panel([
        ('Poblacion total',  _fmt(pob_t),   'hab', True),
        ('Hombres',          _fmt(pob_h),   'hab', False),
        ('Mujeres',          _fmt(pob_m),   'hab', False),
        ('Indigenas',        _fmt(_v(entity_row, 'pob_indigena')), 'personas', False),
        ('Negro / Afro',     _fmt(_v(entity_row, 'pob_negra_afro')), 'personas', False),
    ], title='Indicadores demograficos')


# ══════════════════════════════════════════════════════════════════════════════
# 3. ASEGURAMIENTO EN SALUD
# ══════════════════════════════════════════════════════════════════════════════
_section('Aseguramiento en salud',
         'Afiliacion al SGSSS por regimen y cobertura respecto a la poblacion.',
         anchor='aseguramiento')
_src('aseguramiento', periods)
_aseg_period = (
    period_label if sel_year
    else periods.get('aseguramiento', 'Ultimo disponible')
)
st.caption(f'📅 Datos de afiliacion correspondientes a: **{_aseg_period}**')

nat_cob = _nat_avg(df_dept_all, 'cobertura_pct')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    c_d, c_g = st.columns(2)
    with c_d:
        st.plotly_chart(donut_afil(entity_row), use_container_width=True)
    with c_g:
        st.plotly_chart(
            gauge_pct(_v(entity_row, 'cobertura_pct'), 'Cobertura de afiliacion'),
            use_container_width=True,
        )

with col_data:
    cob_dift = _v(dift_ent, 'cobertura_pts') if dift_ent is not None else None
    _panel([
        ('Cobertura — ' + entity_label, f'{_fmt(cob, 1)}%' if cob else 'N/D', '', True),
        ('Cobertura — ' + sel_dept,
         f'{_fmt(_v(dept_row, "cobertura_pct"), 1)}%', '', False),
        ('Cobertura — Nacional prom.',
         f'{_fmt(nat_cob, 1)}%', '', False),
        ('Subsidiado',    _fmt(_v(entity_row, 'afiliados_subsidiado')),   'afil.', False),
        ('Contributivo',  _fmt(_v(entity_row, 'afiliados_contributivo')), 'afil.', False),
    ], title='Indicadores de aseguramiento')
    if cob_dift:
        st.markdown(_dift_badge(cob_dift), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 4. INFRAESTRUCTURA SANITARIA
# ══════════════════════════════════════════════════════════════════════════════
_section('Infraestructura sanitaria',
         'Prestadores de servicios de salud habilitados y capacidad instalada.',
         anchor='infraestructura')
_src('reps', periods)

nat_ips = _nat_avg(df_dept_all, 'ips_total')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    c_d, c_b = st.columns(2)
    with c_d:
        st.plotly_chart(donut_ips(entity_row), use_container_width=True)
    with c_b:
        st.plotly_chart(
            _cmp_bar(entity_label, _v(entity_row, 'ips_total'),
                     dept_label, _v(dept_row, 'ips_total'), nat_ips,
                     unit='IPS', title='IPS habilitadas vs referencia'),
            use_container_width=True,
        )

with col_data:
    _panel([
        ('IPS — ' + entity_label,     _fmt(_v(entity_row, 'ips_total')),        'IPS', True),
        ('IPS — ' + sel_dept,          _fmt(_v(dept_row,   'ips_total')),        'IPS', False),
        ('IPS — Nacional prom.',        _fmt(nat_ips, 0) if nat_ips else 'N/D',  'IPS', False),
        ('Capacidad instalada',         _fmt(_v(entity_row, 'capacidad_instalada')), 'camas', False),
        ('IPS intervenidas',            _fmt(_v(entity_row, 'ips_intervenidas')), '',    False),
        ('EPS intervenidas',            _fmt(_v(entity_row, 'eps_intervenidas')), '',    False),
    ], title='Indicadores de infraestructura')

if not use_mun:
    with st.expander(f'Top municipios de {sel_dept} por IPS', expanded=False):
        st.plotly_chart(bar_muns_top(df_mun_all, 'ips_total', 'IPS habilitadas'),
                        use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# 5. CALIDAD DEL AGUA — IRCA
# ══════════════════════════════════════════════════════════════════════════════
_section('Calidad del agua — IRCA',
         'Indice de Riesgo de la Calidad del Agua (0 = sin riesgo, 100 = inviable sanitariamente).',
         anchor='irca')
_src('irca', periods)

nat_irca = _nat_avg(df_dept_all, 'irca_promedio')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    c_g, c_b = st.columns(2)
    with c_g:
        irca_val = _v(entity_row, 'irca_promedio')
        irca_lvl = entity_row.get('irca_nivel_riesgo', '') or ''
        st.plotly_chart(gauge_irca(irca_val, irca_lvl), use_container_width=True)
    with c_b:
        st.plotly_chart(
            _cmp_bar(entity_label, irca_val,
                     dept_label, _v(dept_row, 'irca_promedio'), nat_irca,
                     unit='pts IRCA', title='IRCA vs referencia'),
            use_container_width=True,
        )

with col_data:
    irca_muns = (df_mun_all[['municipio', 'irca_promedio', 'irca_nivel_riesgo']]
                 .dropna(subset=['irca_promedio'])
                 .sort_values('irca_promedio', ascending=False)
                 .reset_index(drop=True))
    _panel([
        ('IRCA — ' + entity_label,  _fmt(irca_val, 1),              'pts', True),
        ('IRCA — ' + sel_dept,      _fmt(_v(dept_row, 'irca_promedio'), 1), 'pts', False),
        ('IRCA — Nacional prom.',   _fmt(nat_irca, 1) if nat_irca else 'N/D', 'pts', False),
        ('Nivel de riesgo',         irca_lvl or 'N/D',               '',    False),
    ], title='Indicadores IRCA')
    if not irca_muns.empty:
        st.markdown('**Municipios con mayor IRCA**')
        st.dataframe(irca_muns.head(8), hide_index=True, use_container_width=True,
                     column_config={
                         'municipio':        'Municipio',
                         'irca_promedio':    st.column_config.NumberColumn('IRCA', format='%.1f'),
                         'irca_nivel_riesgo':'Nivel',
                     })


# ══════════════════════════════════════════════════════════════════════════════
# 6. MORTALIDAD MATERNA
# ══════════════════════════════════════════════════════════════════════════════
_section('Mortalidad materna',
         'Razon de mortalidad materna por 100,000 nacidos vivos. '
         'Indicador trazador de calidad de atencion obstetrica.',
         anchor='mortalidad-materna')
_src('mortalidad_materna', periods)

nat_mm = _nat_avg(df_dept_all, 'razon_mortalidad_materna')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(
        _cmp_bar(entity_label, _v(entity_row, 'razon_mortalidad_materna'),
                 dept_label, _v(dept_row, 'razon_mortalidad_materna'), nat_mm,
                 unit='x100k NV', title='Razon de mortalidad materna'),
        use_container_width=True,
    )

with col_data:
    mm_dift = _v(dift_ent, 'mort_materna_pts') if dift_ent is not None else None
    _panel([
        (entity_label,        _fmt(_v(entity_row, 'razon_mortalidad_materna'), 1), 'x100k NV', True),
        (sel_dept,            _fmt(_v(dept_row,   'razon_mortalidad_materna'), 1), 'x100k NV', False),
        ('Nacional (prom.)',  _fmt(nat_mm, 1) if nat_mm else 'N/D',               'x100k NV', False),
    ], title='Razon de mortalidad materna')
    if mm_dift:
        st.markdown(_dift_badge(mm_dift), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 7. SIFILIS CONGENITA
# ══════════════════════════════════════════════════════════════════════════════
_section('Sifilis congenita',
         'Casos acumulados de sifilis congenita (nacidos vivos + muertes fetales). Fuente: informe de entidad territorial INS.',
         anchor='sifilis')
_src('sifilis_congenita', periods)

nat_sc_casos = _nat_avg(df_dept_all, 'casos_sifilis_congenita')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(
        _cmp_bar(entity_label, _v(entity_row, 'casos_sifilis_congenita'),
                 dept_label, _v(dept_row, 'casos_sifilis_congenita'), nat_sc_casos,
                 unit='casos', title='Casos de sifilis congenita'),
        use_container_width=True,
    )

with col_data:
    _panel([
        (entity_label,       _fmt(_v(entity_row, 'casos_sifilis_congenita'), 0), 'casos', True),
        (sel_dept,           _fmt(_v(dept_row,   'casos_sifilis_congenita'), 0), 'casos', False),
        ('Nacional (prom.)', _fmt(nat_sc_casos, 0) if nat_sc_casos else 'N/D',   'casos', False),
    ], title='Casos sifilis congenita')


# ══════════════════════════════════════════════════════════════════════════════
# 8. DESNUTRICION AGUDA
# ══════════════════════════════════════════════════════════════════════════════
_section('Desnutricion aguda (menores de 5 anos)',
         'Prevalencia por 100,000 ninos <5 anos. Indicador critico de seguridad alimentaria.',
         anchor='desnutricion')
_src('desnutricion_aguda', periods)

nat_dnt = _nat_avg(df_dept_all, 'prevalencia_desnutricion_aguda')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(
        _cmp_bar(entity_label, _v(entity_row, 'prevalencia_desnutricion_aguda'),
                 dept_label, _v(dept_row, 'prevalencia_desnutricion_aguda'), nat_dnt,
                 unit='x100k <5', title='Prevalencia de desnutricion aguda'),
        use_container_width=True,
    )

with col_data:
    dnt_dift = (_v(dift_ent, 'desnutricion_pts') if (use_mun and not dift_is_district)
                else _v(dift_ent, 'mort_menores5_pts')) if dift_ent is not None else None
    _panel([
        (entity_label,       _fmt(_v(entity_row, 'prevalencia_desnutricion_aguda'), 1), 'x100k <5', True),
        (sel_dept,           _fmt(_v(dept_row,   'prevalencia_desnutricion_aguda'), 1), 'x100k <5', False),
        ('Nacional (prom.)', _fmt(nat_dnt, 1) if nat_dnt else 'N/D',                   'x100k <5', False),
    ], title='Prevalencia desnutricion aguda')
    if dnt_dift:
        st.markdown(_dift_badge(dnt_dift), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 9. MORTALIDAD EN MENORES DE 5 ANOS  (dept-level)
# ══════════════════════════════════════════════════════════════════════════════
_section('Mortalidad en menores de 5 anos',
         'Tasas por 100,000 menores de 5 anos segun causa. Datos a nivel departamental.',
         anchor='menores5')
_src('mortalidad_menores5', periods)

if use_mun:
    st.info(f'Datos disponibles solo a nivel departamental — mostrando {sel_dept}.')

nat_dnt5 = _nat_avg(df_dept_all, 'tasa_mortalidad_menores5_dnt')
nat_ira5 = _nat_avg(df_dept_all, 'tasa_mortalidad_menores5_ira')
nat_eda5 = _nat_avg(df_dept_all, 'tasa_mortalidad_menores5_eda')
v_dnt5 = _v(dept_row, 'tasa_mortalidad_menores5_dnt')
v_ira5 = _v(dept_row, 'tasa_mortalidad_menores5_ira')
v_eda5 = _v(dept_row, 'tasa_mortalidad_menores5_eda')

col_chart, col_data = st.columns([3, 2])
with col_chart:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(
            bar_comparison(['Nacional', sel_dept], [nat_dnt5, v_dnt5],
                           unit='x100k', title='Desnutricion', entity_idx=1),
            use_container_width=True,
        )
    with c2:
        st.plotly_chart(
            bar_comparison(['Nacional', sel_dept], [nat_ira5, v_ira5],
                           unit='x100k', title='IRA', entity_idx=1),
            use_container_width=True,
        )
    with c3:
        st.plotly_chart(
            bar_comparison(['Nacional', sel_dept], [nat_eda5, v_eda5],
                           unit='x100k', title='EDA', entity_idx=1),
            use_container_width=True,
        )

with col_data:
    _panel([
        (sel_dept + ' — Desnutricion', _fmt(v_dnt5, 1), 'x100k <5', True),
        (sel_dept + ' — IRA',          _fmt(v_ira5, 1), 'x100k <5', False),
        (sel_dept + ' — EDA',          _fmt(v_eda5, 1), 'x100k <5', False),
        ('Nacional — Desnutricion',    _fmt(nat_dnt5, 1) if nat_dnt5 else 'N/D', 'x100k <5', False),
        ('Nacional — IRA',             _fmt(nat_ira5, 1) if nat_ira5 else 'N/D', 'x100k <5', False),
        ('Nacional — EDA',             _fmt(nat_eda5, 1) if nat_eda5 else 'N/D', 'x100k <5', False),
    ], title='Mortalidad menores de 5 anos')


# ══════════════════════════════════════════════════════════════════════════════
# 10. DENGUE  (dept-level)
# ══════════════════════════════════════════════════════════════════════════════
_section('Dengue',
         'Incidencia por 100,000 habitantes. Datos disponibles a nivel departamental.',
         anchor='dengue')
_src('dengue', periods)

if use_mun:
    st.info(f'Datos disponibles solo a nivel departamental — mostrando {sel_dept}.')

nat_dng = _nat_avg(df_dept_all, 'incidencia_dengue_x100k')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(
        bar_comparison(['Nacional (prom.)', sel_dept],
                       [nat_dng, _v(dept_row, 'incidencia_dengue_x100k')],
                       unit='x100k hab', title='Incidencia de dengue', entity_idx=1),
        use_container_width=True,
    )

with col_data:
    dng_dift = _v(dift_ent, 'letalidad_dengue_pts') if dift_ent is not None else None
    _panel([
        (sel_dept,           _fmt(_v(dept_row, 'incidencia_dengue_x100k'), 1), 'x100k', True),
        ('Nacional (prom.)', _fmt(nat_dng, 1) if nat_dng else 'N/D',          'x100k', False),
        ('Dengue total',     _fmt(_v(dept_row, 'dengue_total')),               'casos', False),
        ('Dengue grave',     _fmt(_v(dept_row, 'dengue_grave_total')),         'casos', False),
    ], title='Indicadores de dengue')
    if dng_dift:
        st.markdown(_dift_badge(dng_dift), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 11. SALUD MENTAL — INTENTO DE SUICIDIO
# ══════════════════════════════════════════════════════════════════════════════
_section('Salud mental — Intento de suicidio',
         'Tasa por 100,000 habitantes. Nota: el informe INS cubre departamentos con mayor reporte; Bogota D.C. se incluye en algunos periodos bajo informes de distrito.',
         anchor='suicidio')
_src('intento_suicidio', periods)

nat_sui = _nat_avg(df_dept_all, 'tasa_intento_suicidio')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(
        _cmp_bar(entity_label, _v(entity_row, 'tasa_intento_suicidio'),
                 dept_label, _v(dept_row, 'tasa_intento_suicidio'), nat_sui,
                 unit='x100k hab', title='Tasa de intento de suicidio'),
        use_container_width=True,
    )

with col_data:
    sui_dift = (_v(dift_ent, 'tasa_suicidio_pts') if (not use_mun or dift_is_district) else None) if dift_ent is not None else None
    _panel([
        (entity_label,       _fmt(_v(entity_row, 'tasa_intento_suicidio'), 1), 'x100k', True),
        (sel_dept,           _fmt(_v(dept_row,   'tasa_intento_suicidio'), 1), 'x100k', False),
        ('Nacional (prom.)', _fmt(nat_sui, 1) if nat_sui else 'N/D',           'x100k', False),
    ], title='Tasa intento de suicidio')
    if sui_dift:
        st.markdown(_dift_badge(sui_dift), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 12. VIOLENCIA DE GENERO E INTRAFAMILIAR  (dept-level)
# ══════════════════════════════════════════════════════════════════════════════
_section('Violencia de genero e intrafamiliar',
         'Total de casos notificados (absolutos) y tasa por 100.000 hab. por sub-tipo. Datos a nivel departamental. Nota: Bogota D.C. se reporta como distrito separado en el informe INS.',
         anchor='violencia')
_src('violencia_genero', periods)

if use_mun:
    st.info(f'Datos disponibles solo a nivel departamental — mostrando {sel_dept}.')

nat_viol = _nat_avg(df_dept_all, 'violencia_genero_intrafamiliar')
col_chart, col_data = st.columns([3, 2])
with col_chart:
    st.plotly_chart(bar_violence(dept_row), use_container_width=True)

with col_data:
    _panel([
        ('Total genero/intrafam — ' + sel_dept,
         _fmt(_v(dept_row, 'violencia_genero_intrafamiliar')), 'casos', True),
        ('Nacional (prom.)', _fmt(nat_viol, 0) if nat_viol else 'N/D', 'casos', False),
        ('Violencia fisica',       _fmt(_v(dept_row, 'violencia_fisica'), 1),       'x100k', False),
        ('Violencia psicologica',  _fmt(_v(dept_row, 'violencia_psicologica'), 1),  'x100k', False),
        ('Negligencia/abandono',   _fmt(_v(dept_row, 'negligencia_abandono'), 1),   'x100k', False),
        ('Violencia sexual',       _fmt(_v(dept_row, 'violencia_sexual'), 1),       'x100k', False),
    ], title='Casos de violencia (sub-tipos: tasa x100k)')


# ══════════════════════════════════════════════════════════════════════════════
# 13. DESEMPENO ET 2024 — DIFT18
# ══════════════════════════════════════════════════════════════════════════════
_section('Desempeno ET 2024 — DIFT18',
         'Evaluacion del desempeno de la entidad territorial. Escala 1 (Bajo) a 4 (Optimo).',
         anchor='dift18')
_src('dift18', periods)

if dift_ent is None:
    st.info('Sin datos DIFT18 para esta entidad.')
else:
    avg = _v(dift_ent, 'puntaje_promedio')
    _pts_lbl = {1: 'Bajo', 2: 'En proceso', 3: 'Satisfactorio', 4: 'Optimo'}
    avg_lbl  = _pts_lbl.get(round(avg) if avg else 0, 'N/D')
    avg_color = ('#EF5350' if avg and avg < 2 else
                 '#FFA726' if avg and avg < 3 else
                 '#66BB6A' if avg and avg < 3.5 else '#26A69A')

    col_chart, col_data = st.columns([3, 2])

    if use_mun and not dift_is_district:
        indicators = [
            ('Cobertura afiliacion',    _v(dift_ent, 'cobertura_pts')),
            ('Listado censal',          _v(dift_ent, 'listado_censal_pts')),
            ('SISBEN IV',               _v(dift_ent, 'sisben_pts')),
            ('Mort. materna',           _v(dift_ent, 'mort_materna_pts')),
            ('Mort. menores-5',         _v(dift_ent, 'mort_menores5_pts')),
            ('Desnutricion aguda',      _v(dift_ent, 'desnutricion_pts')),
            ('Letalidad dengue',        _v(dift_ent, 'letalidad_dengue_pts')),
            ('Reporte informacion',     _v(dift_ent, 'reporte_info_pts')),
            ('Equilibrio FLS',          _v(dift_ent, 'equilibrio_fls_pts')),
            ('Ejec. ingresos',          _v(dift_ent, 'ejec_ingresos_pts')),
            ('Ejec. compromisos',       _v(dift_ent, 'ejec_compromisos_pts')),
            ('Ejec. obligaciones',      _v(dift_ent, 'ejec_obligaciones_pts')),
            ('Ejec. pagos',             _v(dift_ent, 'ejec_pagos_pts')),
            ('SGP Subsidiado',          _v(dift_ent, 'sgp_subsidiado_pts')),
            ('SGP Salud publica comp.', _v(dift_ent, 'sgp_sp_comp_pts')),
            ('SGP Salud publica oblig.',_v(dift_ent, 'sgp_sp_oblig_pts')),
            ('Reporte SNS Juegos',      _v(dift_ent, 'reporte_sns_juegos_pts')),
        ]
    else:
        indicators = [
            ('Inspeccion/vigilancia',  _v(dift_ent, 'inspva_pts')),
            ('Calidad GAUDI',          _v(dift_ent, 'calidad_gaudi_pts')),
            ('Cobertura afiliacion',   _v(dift_ent, 'cobertura_pts')),
            ('Habilitacion IPS',       _v(dift_ent, 'habilitacion_pts')),
            ('Visitas IPS',            _v(dift_ent, 'visitas_ips_pts')),
            ('PAMEC',                  _v(dift_ent, 'pamec_pts')),
            ('LVR-CRUE',               _v(dift_ent, 'lvr_crue_pts')),
            ('Letalidad dengue',       _v(dift_ent, 'letalidad_dengue_pts')),
            ('Mort. menores-5',        _v(dift_ent, 'mort_menores5_pts')),
            ('Mort. materna',          _v(dift_ent, 'mort_materna_pts')),
            ('Tasa suicidio',          _v(dift_ent, 'tasa_suicidio_pts')),
            ('Equilibrio FLS',         _v(dift_ent, 'equilibrio_fls_pts')),
            ('Ejec. ingresos',         _v(dift_ent, 'ejec_ingresos_pts')),
            ('Ejec. compromisos',      _v(dift_ent, 'ejec_compromisos_pts')),
            ('Ejec. obligaciones',     _v(dift_ent, 'ejec_obligaciones_pts')),
            ('Ejec. pagos',            _v(dift_ent, 'ejec_pagos_pts')),
            ('SGP Salud publica',      _v(dift_ent, 'sgp_sp_comp_pts')),
            ('Deuda esfuerzo propio',  _v(dift_ent, 'deuda_esfuerzo_pts')),
        ]

    entity_name = sel_mun if use_mun else sel_dept
    with col_chart:
        st.plotly_chart(
            bar_dift18_scores(indicators, f'Puntajes DIFT18 — {entity_name}'),
            use_container_width=True,
        )

    with col_data:
        st.markdown(
            f'<div style="background:{avg_color};color:white;border-radius:14px;padding:20px;text-align:center;margin-bottom:12px">'
            f'<div style="font-size:13px;opacity:0.85;text-transform:uppercase;letter-spacing:0.5px">Puntaje promedio</div>'
            f'<div style="font-size:48px;font-weight:800;line-height:1.1">{f"{avg:.2f}" if avg else "N/D"}</div>'
            f'<div style="font-size:16px;font-weight:600;margin-top:4px">{avg_lbl}</div>'
            f'<div style="font-size:12px;opacity:0.75;margin-top:2px">Escala 1 – 4</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        ind_rows = [{'Indicador': lbl, 'Puntaje': int(pts) if pts else None,
                     'Nivel': _pts_lbl.get(round(float(pts)), 'N/D') if pts else 'N/D'}
                    for lbl, pts in indicators if pts is not None]
        if ind_rows:
            st.dataframe(
                pd.DataFrame(ind_rows), hide_index=True, use_container_width=True,
                height=min(400, len(ind_rows) * 36 + 40),
                column_config={
                    'Indicador': st.column_config.TextColumn('Indicador'),
                    'Puntaje':   st.column_config.NumberColumn('Pts', format='%d'),
                    'Nivel':     st.column_config.TextColumn('Nivel'),
                },
            )


# ══════════════════════════════════════════════════════════════════════════════
# 14. TABLA CONSOLIDADA DE INDICADORES
# ══════════════════════════════════════════════════════════════════════════════
_section('Tabla consolidada de indicadores',
         'Resumen de todos los indicadores disponibles para la entidad seleccionada.',
         anchor='tabla')

# (category, label, col, unit, dept_only)
# dept_only=True: mun column shows dept value + note; False: shows mun value directly
_METRICS_DEF = [
    # ── Demografía ─────────────────────────────────────────────────────────────
    ('Demografía',   'Poblacion total',          'pob_total',                   'hab',       False),
    ('Demografía',   'Hombres',                  'pob_hombres',                 'hab',       False),
    ('Demografía',   'Mujeres',                  'pob_mujeres',                 'hab',       False),
    ('Demografía',   'Indigenas',                'pob_indigena',                'personas',  False),
    ('Demografía',   'Negro / Afro',             'pob_negra_afro',              'personas',  False),
    ('Demografía',   'Gitano / Rrom',            'pob_gitana_rrom',             'personas',  False),
    ('Demografía',   'Raizal',                   'pob_raizal',                  'personas',  False),
    ('Demografía',   'Palenquera',               'pob_palenquera',              'personas',  False),
    ('Demografía',   'Sin pertenencia etnica',   'pob_ninguno',                 'personas',  False),
    # ── Aseguramiento ──────────────────────────────────────────────────────────
    ('Aseguramiento','Afiliados total',           'afiliados_total',             'afil.',     False),
    ('Aseguramiento','Afiliados subsidiado',      'afiliados_subsidiado',        'afil.',     False),
    ('Aseguramiento','Afiliados contributivo',    'afiliados_contributivo',      'afil.',     False),
    ('Aseguramiento','Cobertura de afiliacion',   'cobertura_pct',               '%',         False),
    # ── Infraestructura ────────────────────────────────────────────────────────
    ('Infraestructura','IPS total',              'ips_total',                   'IPS',       False),
    ('Infraestructura','IPS publica',            'ips_publica',                 'IPS',       False),
    ('Infraestructura','IPS privada',            'ips_privada',                 'IPS',       False),
    ('Infraestructura','IPS mixta',              'ips_mixta',                   'IPS',       False),
    ('Infraestructura','Capacidad instalada',    'capacidad_instalada',         'camas',     False),
    ('Infraestructura','IPS intervenidas',       'ips_intervenidas',            '',          True),
    ('Infraestructura','EPS intervenidas',       'eps_intervenidas',            '',          True),
    # ── Calidad del agua ───────────────────────────────────────────────────────
    ('Calidad del agua','IRCA promedio',         'irca_promedio',               'pts',       False),
    # ── Salud publica ──────────────────────────────────────────────────────────
    ('Salud publica','Mortalidad materna',        'razon_mortalidad_materna',    'x100k NV',  False),
    ('Salud publica','Sifilis congenita',         'casos_sifilis_congenita',    'casos',     False),
    ('Salud publica','Desnutricion aguda',        'prevalencia_desnutricion_aguda','x100k <5',False),
    ('Salud publica','Mort. <5 desnutricion',     'tasa_mortalidad_menores5_dnt','x100k <5',  True),
    ('Salud publica','Mort. <5 IRA',              'tasa_mortalidad_menores5_ira','x100k <5',  True),
    ('Salud publica','Mort. <5 EDA',              'tasa_mortalidad_menores5_eda','x100k <5',  True),
    ('Salud publica','Dengue incidencia',         'incidencia_dengue_x100k',    'x100k',     True),
    ('Salud publica','Dengue total casos',        'dengue_total',               'casos',     True),
    ('Salud publica','Dengue grave',              'dengue_grave_total',          'casos',     True),
    ('Salud publica','Intento de suicidio',       'tasa_intento_suicidio',      'x100k',     False),
    # ── Violencia ──────────────────────────────────────────────────────────────
    ('Violencia',    'Total genero/intrafamiliar','violencia_genero_intrafamiliar','casos',   True),
    ('Violencia',    'Violencia fisica',           'violencia_fisica',           'x100k',    True),
    ('Violencia',    'Violencia psicologica',      'violencia_psicologica',      'x100k',    True),
    ('Violencia',    'Negligencia / abandono',     'negligencia_abandono',       'x100k',    True),
    ('Violencia',    'Violencia sexual',           'violencia_sexual',           'x100k',    True),
]

def _fmtn(val, unit='') -> str:
    """Format a numeric value for the consolidated table."""
    if val is None or pd.isna(val):
        return '—'
    try:
        f = float(val)
        if unit == '%':
            return f'{f:.1f} %'
        if unit in ('pts', 'x100k NV', 'x100k <5', 'x100k'):
            return f'{f:,.1f}'
        return f'{f:,.0f}'
    except (TypeError, ValueError):
        return str(val)

# Build consolidated rows
nat_row = {col: _nat_avg(df_dept_all, col) for _, _, col, _, _ in _METRICS_DEF}

tbl_rows = []
for cat, label, col, unit, dept_only in _METRICS_DEF:
    d_val = _v(dept_row, col)
    if use_mun and not dept_only:
        m_val = _v(mun_row, col)
        m_fmt = _fmtn(m_val, unit)
    elif use_mun and dept_only:
        m_val = d_val          # dept-level metric: repeat dept value for mun column
        m_fmt = _fmtn(m_val, unit) + ' *'
    else:
        m_val = None
        m_fmt = '—'

    tbl_rows.append({
        'Categoria':           cat,
        'Indicador':           label,
        'Unidad':              unit,
        sel_dept:              _fmtn(d_val, unit),
        sel_mun if use_mun else 'Municipio': m_fmt,
        'Nacional (prom.)':    _fmtn(nat_row.get(col), unit),
        # Raw values for conditional coloring
        '_dept_raw':           float(d_val)  if d_val  is not None and not pd.isna(d_val)  else None,
        '_mun_raw':            float(m_val)  if m_val  is not None and not pd.isna(m_val)  else None,
        '_nat_raw':            float(nat_row.get(col)) if nat_row.get(col) is not None and not pd.isna(nat_row.get(col)) else None,
    })

df_tbl = pd.DataFrame(tbl_rows)

# Display columns (drop raw helper cols)
display_cols = ['Categoria', 'Indicador', 'Unidad',
                sel_dept,
                sel_mun if use_mun else 'Municipio',
                'Nacional (prom.)']
display_cols = list(dict.fromkeys(display_cols))   # deduplicate if dept == mun label

mun_col_lbl = sel_mun if use_mun else 'Municipio'

st.dataframe(
    df_tbl[display_cols],
    use_container_width=True,
    hide_index=True,
    height=min(900, len(tbl_rows) * 36 + 42),
    column_config={
        'Categoria':        st.column_config.TextColumn('Categoria',   width='small'),
        'Indicador':        st.column_config.TextColumn('Indicador',   width='medium'),
        'Unidad':           st.column_config.TextColumn('Unidad',      width='small'),
        sel_dept:           st.column_config.TextColumn(sel_dept,      width='medium'),
        mun_col_lbl:        st.column_config.TextColumn(mun_col_lbl,   width='medium'),
        'Nacional (prom.)': st.column_config.TextColumn('Nacional prom.', width='medium'),
    },
)

if use_mun:
    st.caption('* Indicador disponible solo a nivel departamental — se muestra el valor del departamento.')

# Download button
csv_bytes = df_tbl[display_cols].to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
st.download_button(
    label='Descargar tabla (CSV)',
    data=csv_bytes,
    file_name=f'indicadores_{sel_dept}{"_" + sel_mun if use_mun else ""}.csv',
    mime='text/csv',
)