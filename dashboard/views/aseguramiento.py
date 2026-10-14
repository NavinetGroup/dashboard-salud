# -*- coding: utf-8 -*-
"""Aseguramiento — cobertura y afiliación (FCT)."""

import streamlit as st

from charts import pyramid_regimen, ring_pct
from data import get_monthly_series, get_piramide
from registry import MODULES, SISBEN, get
from ui import chart, footer, kpi_card, module_header, panel, trend_box, _v

sel = st.session_state['sel']
color = MODULES['aseguramiento'][1]
row, prev = sel.entity_row, sel.prev_entity

module_header('aseguramiento', 'Indicadores de cobertura y afiliación', sel)

# EPS with affiliates (BDUA) + EPS intervenidas + affiliated population by regime
top = [get(k) for k in ('eps_total', 'eps_contrib', 'eps_subs', 'eps_interv', 'afil_subs', 'afil_contrib')]
for n, (col, ind) in enumerate(zip(st.columns(6), top), start=1):
    with col:
        r, p, note = (row, prev, '')
        if ind.key == 'eps_interv':
            r, p = sel.dept_row, sel.prev_dept
            note = f'Sede en {sel.dept_name}' if sel.use_mun else 'Por sede de la EPS'
        kpi_card('aseguramiento', ind, r, p, note, num=n)

c_ring, c_pyr = st.columns([2, 3])
with c_ring, panel('aseguramiento', '7. Cobertura de afiliación (%)', 'verified'):
    ind = get('cobertura')
    chart(ring_pct(_v(row, ind.col), color, 'afiliados / población', height=262), key='ring')
    st.markdown(trend_box(ind, _v(row, ind.col), _v(prev, ind.col), _v(prev, ind.period_col),
                         _v(row, ind.period_col))
                + f'<div class="fct-panel-sub" style="margin-top:6px">Datos: {_v(row, ind.period_col) or "N/D"}'
                  ' · MinSalud limita la cobertura municipal a 100 %</div>', unsafe_allow_html=True)
with c_pyr:
    level = 'municipio' if sel.use_mun else 'departamento'
    pyr = get_piramide(level, sel.mun_code if sel.use_mun else sel.dept_code)
    with panel('aseguramiento', 'Pirámide poblacional afiliada', 'stacked_bar_chart'):
        if pyr.empty:
            st.caption('Sin datos BDUA para esta entidad.')
        else:
            tot = pyr.groupby('regimen')['afiliados'].sum()
            chart(pyramid_regimen(pyr, height=300), key='piramide')
            st.markdown(
                f'<div class="fct-panel-sub" style="margin-top:6px">Subsidiado {tot.get("subsidiado", 0):,.0f} · '
                f'Contributivo {tot.get("contributivo", 0):,.0f} afiliados · BDUA con corte '
                f'{str(pyr["fecha_corte"].iloc[0])[:10]}</div>'.replace(',', '.'), unsafe_allow_html=True)

with panel('aseguramiento', 'Afiliados al régimen subsidiado sin Sisbén IV', 'badge',
           'Porcentaje sobre el total de afiliados al régimen subsidiado; la línea muestra la evolución mensual'):
    code = sel.mun_code if sel.use_mun else sel.dept_code
    series = get_monthly_series(level, tuple(i.col for i in SISBEN), code)
    subs = _v(row, 'afiliados_subsidiado')
    for n, (col, ind) in enumerate(zip(st.columns(4), SISBEN), start=8):
        with col:
            v = _v(row, ind.col)
            share = f'{v / subs * 100:.1f}% del régimen subsidiado'.replace('.', ',') if v is not None and subs else ''
            spark = series[ind.col].dropna().tolist() if not series.empty and ind.col in series else None
            kpi_card('aseguramiento', ind, row, prev, share, spark=spark, num=n)

footer('Los indicadores permiten monitorear la cobertura, distribución y características de la '
       'afiliación al Sistema General de Seguridad Social en Salud en el territorio.', ['bdua', 'supersalud'])
