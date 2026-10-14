# -*- coding: utf-8 -*-
"""Inicio — module menu (FCT mockup: the Ficha as "módulo principal", then one
full-width coloured band per module, each band a link to its page)."""

import html

import streamlit as st

from registry import MODULES

sel = st.session_state['sel']

st.markdown(
    '<div class="fct-header" style="background:linear-gradient(90deg,#0B5D5E,#26A69A)">'
    '<h1>INFORME REGIONAL DE SALUD</h1>'
    '<p>Caracterización del sistema de salud por departamento y municipio</p>'
    f'<div class="fct-crumb">{html.escape(sel.entity_name)} · {html.escape(sel.period_label)}</div></div>',
    unsafe_allow_html=True)

PAGES = {
    'ficha':          'views/ficha.py',
    'demograficos':   'views/demograficos.py',
    'salud_publica':  'views/salud_publica.py',
    'aseguramiento':  'views/aseguramiento.py',
    'prestacion':     'views/prestacion.py',
    'financiamiento': 'views/financiamiento.py',
}

# Each band is an st.page_link styled as the mockup's card: icon in a white
# circle, title in white capitals, chevron on the right. The Ficha band is
# darker and carries the "MÓDULO PRINCIPAL" chip.
bands = '\n'.join(f"""
.st-key-menu-{k} a {{ background: linear-gradient(90deg, {c} 0%, {c}E6 100%) !important; }}
.st-key-menu-{k} a [data-testid="stIconMaterial"] {{ color: {c} !important; }}""" for k, (_, c, _) in MODULES.items())
st.markdown(f"""
<style>
[class*="st-key-menu-"] {{ max-width: 980px; margin: 0 auto; }}
[class*="st-key-menu-"] [data-testid="stElementContainer"],
[class*="st-key-menu-"] [data-testid="stPageLink"],
[class*="st-key-menu-"] [data-testid="stPageLink"] > div {{ width: 100% !important; max-width: none !important; }}
[class*="st-key-menu-"] a {{
    display: flex !important; align-items: center; gap: 22px; width: 100%;
    min-height: 96px; padding: 14px 64px 14px 22px !important; border-radius: 18px !important;
    box-shadow: 0 3px 12px rgba(0,0,0,.12); position: relative; text-decoration: none !important;
    transition: transform .08s ease, box-shadow .08s ease; }}
[class*="st-key-menu-"] a:hover {{ transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,.18); }}
[class*="st-key-menu-"] a [data-testid="stIconMaterial"] {{
    background: #FFFFFF; border-radius: 50%; width: 64px; height: 64px; min-width: 64px;
    display: flex; align-items: center; justify-content: center; font-size: 36px !important; }}
[class*="st-key-menu-"] a p, [class*="st-key-menu-"] a span {{
    color: #FFFFFF !important; font-size: 25px !important; font-weight: 800 !important;
    letter-spacing: .4px; text-transform: uppercase; line-height: 1.15; }}
[class*="st-key-menu-"] a::after {{
    content: '›'; position: absolute; right: 22px; top: 50%; transform: translateY(-52%);
    width: 36px; height: 36px; border: 2px solid rgba(255,255,255,.85); border-radius: 50%;
    color: #FFFFFF; font-size: 26px; line-height: 30px; text-align: center; }}
.st-key-menu-ficha a {{ min-height: 128px; border: 2px solid #4DD0C4; }}
.st-key-menu-ficha a::before {{
    content: 'MÓDULO PRINCIPAL'; position: absolute; left: 22px; top: 10px; background: #26A69A;
    color: #FFFFFF; font-size: 11px; font-weight: 800; letter-spacing: .6px; padding: 3px 10px;
    border-radius: 10px; }}
.st-key-menu-ficha a [data-testid="stIconMaterial"] {{ margin-top: 14px; }}
.st-key-menu-ficha a p, .st-key-menu-ficha a span {{ font-size: 28px !important; margin-top: 14px; }}
{bands}
</style>""", unsafe_allow_html=True)

for key, path in PAGES.items():
    title, _, icon = MODULES[key]
    with st.container(key=f'menu-{key}'):
        st.page_link(path, label=title, icon=f':material/{icon}:')

st.caption('Seleccione el periodo, el departamento y (opcional) el municipio en los filtros de la barra '
           'lateral. La selección se mantiene al cambiar de módulo.')
