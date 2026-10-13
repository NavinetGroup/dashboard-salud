# -*- coding: utf-8 -*-
"""Inicio — module menu (FCT mockup: six coloured cards)."""

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
    'ficha':          ('views/ficha.py',          'Perfil integral del sistema de salud territorial'),
    'demograficos':   ('views/demograficos.py',   'Caracterización poblacional del territorio'),
    'salud_publica':  ('views/salud_publica.py',  'Indicadores de salud y gestión del riesgo'),
    'aseguramiento':  ('views/aseguramiento.py',  'Cobertura y afiliación'),
    'prestacion':     ('views/prestacion.py',     'Oferta y capacidad de la red de prestadores'),
    'financiamiento': ('views/financiamiento.py', 'Ejecución presupuestal y flujos de recursos'),
}

st.markdown("""
<style>
[class*="st-key-menu-"] { border-radius: 16px !important; padding: 10px 14px; min-height: 175px; }
[class*="st-key-menu-"] p { color: white !important; }
[class*="st-key-menu-"] a { color: white !important; font-weight: 700; }
</style>""", unsafe_allow_html=True)
st.markdown('\n'.join(
    f'<style>.st-key-menu-{k} {{ background: {c} !important; }}</style>'
    for k, (_, c, _) in MODULES.items()), unsafe_allow_html=True)

keys = list(MODULES)
for i in range(0, len(keys), 3):
    for col, key in zip(st.columns(3), keys[i:i + 3]):
        title, _, icon = MODULES[key]
        path, desc = PAGES[key]
        with col, st.container(key=f'menu-{key}'):
            st.markdown(f'### :material/{icon}: {title}')
            st.markdown(desc)
            st.page_link(path, label='Abrir', icon=':material/arrow_forward:')

st.caption('Seleccione el periodo, el departamento y (opcional) el municipio en la barra lateral. '
           'La selección se mantiene al cambiar de módulo.')
