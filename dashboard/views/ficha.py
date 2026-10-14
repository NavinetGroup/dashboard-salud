# -*- coding: utf-8 -*-
"""Ficha de caracterización territorial — one-page summary, one band per module."""

import html

import streamlit as st

from registry import FICHA, MODULES, get
from ui import CARD_H, footer, kpi_card, module_header, share_note, _v

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
    if ind.key == 'ips_interv':   # Supersalud lists them by department
        return sel.dept_row, sel.prev_dept, f'Departamento de {sel.dept_name}' if sel.use_mun else ''
    if ind.col and sel.use_mun and (ind.dept_only or ind.key == 'eps_interv') \
            and _v(sel.mun_row, ind.col) is None:
        return sel.dept_row, sel.prev_dept, f'Valor de {sel.dept_name}'
    return sel.entity_row, sel.prev_entity, ''


# Band panel = one card tall, so each module row is a clean strip of equal height;
# the band column has the same width in every row and the cards fill the rest.
SLOTS = 5
st.markdown(f'''<style>
.fct-band {{ height: {CARD_H}px; border-radius: 14px; padding: 14px 16px; color: white;
    display: flex; flex-direction: column; justify-content: center; gap: 6px; margin-bottom: 14px;
    box-shadow: 0 2px 10px rgba(0,0,0,.10); }}
.fct-band .num {{ display: flex; align-items: center; gap: 10px; font-size: 30px; font-weight: 800; }}
.fct-band .num .fct-ico {{ color: white; font-size: 30px; line-height: 30px; }}
.fct-band .t {{ font-size: 15px; font-weight: 800; letter-spacing: .3px; line-height: 1.2; }}
.fct-band .s {{ font-size: 13px; opacity: .9; }}
</style>''', unsafe_allow_html=True)

for n, (module, keys) in enumerate(FICHA.items(), start=1):
    title, color, icon = MODULES[module]
    # band column fixed; the cards share the rest of the row (4 or 5 per band)
    cols = st.columns([1.0] + [SLOTS / len(keys)] * len(keys))
    with cols[0]:
        st.markdown(f'<div class="fct-band" style="background:linear-gradient(160deg,{color},{color}D9)">'
                    f'<div class="num">{n}<span class="fct-ico">{icon}</span></div>'
                    f'<div class="t">{html.escape(title.upper())}</div>'
                    f'<div class="s">{html.escape(SUBTITLES[module])}</div></div>', unsafe_allow_html=True)
    for col, key in zip(cols[1:], keys):
        ind = get(key)
        with col:
            row, prev, note = _pick(ind)
            note = ' · '.join(x for x in (share_note(ind, row), note) if x)
            kpi_card(module, ind, row, prev, note)

footer('Los indicadores permiten monitorear el desempeño integral del sistema de salud y orientar '
       'acciones para mejorar la salud de la población. Cada módulo amplía el detalle.',
       ['dane', 'sivigila', 'ins_vsp', 'bdua', 'reps', 'supersalud', 'cuipo', 'sicodis', 'cofin'])
