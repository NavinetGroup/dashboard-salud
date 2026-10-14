# -*- coding: utf-8 -*-
"""Salud pública — 11 indicadores de salud y gestión del riesgo (FCT)."""

import streamlit as st

from registry import SALUD_PUBLICA
from ui import footer, kpi_card, module_header, _v

sel = st.session_state['sel']

module_header('salud_publica', 'Indicadores de salud y gestión del riesgo', sel)


def _pick(ind):
    """The municipality's own value when it has one (INS lists only some
    municipalities; districts report as entities), else its department's."""
    if ind.col is None:
        return None, None, ''
    cols = [ind.col] + ([ind.fallback[0]] if ind.fallback else [])
    if sel.use_mun and any(_v(sel.mun_row, c) is not None for c in cols):
        return sel.mun_row, sel.prev_mun, ''
    if sel.use_mun:
        return sel.dept_row, sel.prev_dept, f'Sin dato municipal: valor de {sel.dept_name}'
    return sel.dept_row, sel.prev_dept, ''


inds = SALUD_PUBLICA
for i in range(0, len(inds), 4):
    for col, ind in zip(st.columns(4), inds[i:i + 4]):
        with col:
            row, prev, note = _pick(ind)
            if ind.key == 'irca':
                lvl = _v(row, 'irca_nivel_riesgo')
                note = ' · '.join(x for x in (f'Riesgo: {lvl}' if lvl else '', note) if x)
            if ind.key in ('dnt', 'suicidio') and not sel.use_mun and _v(row, ind.col) is None:
                n = _v(sel.dept_row, 'desnutricion_municipios_reportados' if ind.key == 'dnt'
                       else 'suicidio_municipios_reportados')
                if n:
                    note = f'Calculado sobre {int(n)} municipio(s) listados en el boletín INS'
            kpi_card('salud_publica', ind, row, prev, note)

st.markdown("""
<div style="display:flex;gap:28px;font-size:12.5px;color:#455A64;margin-top:8px">
  <span style="color:#2E7D32">▼ / ▲ verde: cambio favorable respecto al mismo periodo del año anterior</span>
  <span style="color:#C62828">▲ / ▼ rojo: cambio desfavorable</span>
  <span style="color:#F9A825">► sin cambio significativo</span>
</div>""", unsafe_allow_html=True)

footer('Los indicadores permiten monitorear las condiciones de salud de la población y la gestión '
       'integral del riesgo. Las tasas INS son acumuladas en el año hasta el periodo indicado; la '
       'tendencia compara con el mismo periodo del año anterior.', ['sivigila', 'sivicap', 'dane'])
