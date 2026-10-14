# -*- coding: utf-8 -*-
"""Salud pública — 11 indicadores de salud y gestión del riesgo (FCT)."""

import streamlit as st

from registry import SALUD_PUBLICA
from ui import footer, kpi_card, mini_donut_html, module_header, scale_html, _v

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


# IRCA risk bands (Resolución 2115 de 2007) and a five-step scale for capacities
_IRCA_BANDS = [(5, '#43A047'), (14, '#9CCC65'), (35, '#FDD835'), (80, '#FB8C00'), (100, '#E53935')]
_IRCA_LEVEL = ['Sin riesgo', 'Bajo', 'Medio', 'Alto', 'Inviable sanitariamente']
_CAP_BANDS = [(20, '#E53935'), (40, '#FB8C00'), (60, '#FDD835'), (80, '#9CCC65'), (100, '#43A047')]
_CAP_LEVEL = [(20, 'Muy bajo'), (40, 'Bajo'), (60, 'Medio'), (80, 'Alto'), (101, 'Muy alto')]


def _visual(ind, row) -> str:
    v = _v(row, ind.col)
    if ind.key == 'irca' and v is not None:
        # SIVICAP's level when the row has it (municipalities), else from the value
        k = next(i for i, (b, _) in enumerate(_IRCA_BANDS) if float(v) <= b or b == 100)
        lvl = _v(row, 'irca_nivel_riesgo') or _IRCA_LEVEL[k]
        return scale_html(v, _IRCA_BANDS, ticks=[0, 5, 14, 35, 80, 100],
                          level=f'Riesgo: {str(lvl).lower()}', level_color=_IRCA_BANDS[k][1]
                          if k not in (1, 2) else '#8D6E00')
    if ind.key == 'capacidades' and v is not None:
        lvl = next(l for b, l in _CAP_LEVEL if float(v) < b)
        return scale_html(v, _CAP_BANDS, ticks=[0, 20, 40, 60, 80, 100], level=f'Nivel de capacidad: {lvl}')
    if ind.key == 'vsp' and _v(row, 'vsp_cumple') is not None:
        return mini_donut_html([(_v(row, 'vsp_cumple'), '#26A69A', 'Cumple'),
                                (_v(row, 'vsp_parcial'), '#FBC02D', 'Parcial'),
                                (_v(row, 'vsp_nocumple'), '#E53935', 'No cumple')], size=58)
    return ''


inds = SALUD_PUBLICA
for i in range(0, len(inds), 4):
    for j, (col, ind) in enumerate(zip(st.columns(4), inds[i:i + 4])):
        with col:
            row, prev, note = _pick(ind)
            if ind.key == 'sifilis' and _v(row, 'sv_sifilis_casos') is not None:
                n = int(_v(row, 'sv_sifilis_casos'))
                note = ' · '.join(x for x in (f'{n:,} caso{"s" if n != 1 else ""}'.replace(',', '.'), note) if x)
            if ind.key == 'vsp' and _v(row, 'vsp_subindicadores') is not None:
                note = ' · '.join(x for x in (f'{int(_v(row, "vsp_subindicadores"))} subindicadores evaluados',
                                              note) if x)
            if ind.key in ('dnt', 'suicidio') and not sel.use_mun and _v(row, ind.col) is None:
                n = _v(sel.dept_row, 'desnutricion_municipios_reportados' if ind.key == 'dnt'
                       else 'suicidio_municipios_reportados')
                if n:
                    note = f'Calculado sobre {int(n)} municipio(s) listados en el boletín INS'
            kpi_card('salud_publica', ind, row, prev, note, num=i + j + 1, visual=_visual(ind, row))

# Convenciones (mockup): what the trend colours mean
st.markdown("""
<div class="fct-conv">
  <div class="h">CONVENCIONES</div>
  <div><span class="d" style="background:#E8F5E9;color:#2E7D32">▼▲</span> Cambio favorable respecto al mismo periodo del año anterior</div>
  <div><span class="d" style="background:#FFF8E1;color:#F9A825">►</span> Sin cambio significativo, o indicador sin dirección favorable</div>
  <div><span class="d" style="background:#FDECEA;color:#C62828">▲▼</span> Cambio desfavorable respecto al mismo periodo del año anterior</div>
</div>""", unsafe_allow_html=True)

footer('Los indicadores permiten monitorear las condiciones de salud de la población y la gestión '
       'integral del riesgo. Las tasas INS son acumuladas en el año hasta el periodo indicado; la '
       'tendencia compara con el mismo periodo del año anterior. Sífilis congénita: denominador DANE del año, o del '
       'último año completo publicado mientras el año está en curso.', ['sivigila', 'sivicap', 'dane', 'eevv'])
