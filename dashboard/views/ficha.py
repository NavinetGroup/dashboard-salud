# -*- coding: utf-8 -*-
"""Ficha de caracterización territorial — one-page summary, one band per module."""

import html

import streamlit as st

from registry import FICHA, MODULES, get
from ui import footer, kpi_card, module_header, _v

sel = st.session_state['sel']

module_header('ficha', 'Perfil integral del sistema de salud territorial', sel)

SUBTITLES = {
    'demograficos': 'Caracterización poblacional',
    'salud_publica': 'Resultados en salud',
    'aseguramiento': 'Cobertura y afiliación',
    'prestacion': 'Oferta y capacidad de la red',
    'financiamiento': 'Ejecución y flujo de recursos',
}


def _pick(ind):
    if ind.col and sel.use_mun and (ind.dept_only or ind.key == 'eps_interv') \
            and _v(sel.mun_row, ind.col) is None:
        return sel.dept_row, sel.prev_dept, f'Valor de {sel.dept_name}'
    return sel.entity_row, sel.prev_entity, ''


st.markdown('<style>[class*="st-key-band-"] { border-radius: 14px; padding: 14px 16px; color: white; '
            'min-height: 178px; } [class*="st-key-band-"] p { color: white !important; }</style>'
            + ''.join(f'<style>.st-key-band-{m} {{ background: {MODULES[m][1]}; }}</style>' for m in FICHA),
            unsafe_allow_html=True)

for n, (module, keys) in enumerate(FICHA.items(), start=1):
    title, _, icon = MODULES[module]
    cols = st.columns([1.25] + [1] * len(keys))
    with cols[0], st.container(key=f'band-{module}'):
        st.markdown(f'### {n} :material/{icon}:')
        st.markdown(f'**{html.escape(title.upper())}**  \n{SUBTITLES[module]}')
    for col, key in zip(cols[1:], keys):
        ind = get(key)
        with col:
            row, prev, note = _pick(ind)
            kpi_card(module, ind, row, prev, note)

footer('Los indicadores permiten monitorear el desempeño integral del sistema de salud y orientar '
       'acciones para mejorar la salud de la población. Cada módulo amplía el detalle.',
       ['dane', 'sivigila', 'bdua', 'reps', 'supersalud'])
