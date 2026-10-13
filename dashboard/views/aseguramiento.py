# -*- coding: utf-8 -*-
"""Aseguramiento — cobertura y afiliación (FCT)."""

import streamlit as st

from charts import ring_pct, sparkline
from data import get_monthly_series
from registry import MODULES, SISBEN, Indicator, get
from ui import fmt, footer, kpi_card, module_header, pending_card, trend_md, _v

sel = st.session_state['sel']
color = MODULES['aseguramiento'][1]
row, prev = sel.entity_row, sel.prev_entity

module_header('aseguramiento', 'Indicadores de cobertura y afiliación', sel)

# EPS counts (pending BDUA) + EPS intervenidas + affiliated population by regime
top = [get(k) for k in ('eps_total', 'eps_contrib', 'eps_subs', 'eps_interv', 'afil_subs', 'afil_contrib')]
for col, ind in zip(st.columns(6), top):
    with col:
        r, p, note = (row, prev, '')
        if ind.key == 'eps_interv':
            r, p = sel.dept_row, sel.prev_dept
            note = f'Sede en {sel.dept_name}' if sel.use_mun else 'Por sede de la EPS'
        kpi_card('aseguramiento', ind, r, p, note)

c_ring, c_pyr = st.columns([2, 3])
with c_ring:
    with st.container(border=True, key='card-aseguramiento-cobertura-ring'):
        ind = get('cobertura')
        st.markdown(f':material/{ind.icon}: <span class="fct-label">{ind.label} (%)</span>',
                    unsafe_allow_html=True)
        st.plotly_chart(ring_pct(_v(row, ind.col), color, 'afiliados / población'),
                        use_container_width=True)
        st.markdown(trend_md(ind, _v(row, ind.col), _v(prev, ind.col), _v(prev, ind.period_col),
                             _v(row, ind.period_col))
                    + f'<div class="fct-period">Datos: {_v(row, ind.period_col) or "N/D"} · '
                      'MinSalud limita la cobertura municipal a 100%</div>',
                    unsafe_allow_html=True)
with c_pyr:
    pending_card('aseguramiento', Indicator(
        'piramide', 'Pirámide poblacional afiliada (subsidiado / contributivo)', None, icon='stacked_bar_chart',
        pending='BDUA por sexo y grupo de edad (datos.gov.co): por integrar. Solo publica el mes '
                'vigente, por lo que se archivará una copia mensual.'))

st.markdown('#### Afiliados al régimen subsidiado sin Sisbén IV')
code = sel.mun_code if sel.use_mun else sel.dept_code
level = 'municipio' if sel.use_mun else 'departamento'
series = get_monthly_series(level, tuple(i.col for i in SISBEN), code)
subs = _v(row, 'afiliados_subsidiado')
for col, ind in zip(st.columns(4), SISBEN):
    with col:
        v = _v(row, ind.col)
        share = f'{v / subs * 100:.1f}% del régimen subsidiado'.replace('.', ',') if v is not None and subs else ''
        kpi_card('aseguramiento', ind, row, prev, share)
        if not series.empty and series[ind.col].notna().sum() > 1:
            s = series.dropna(subset=[ind.col])
            st.plotly_chart(sparkline((s['mes'].str[:3] + ' ' + s['anio'].astype(str)).tolist(),
                                      s[ind.col].tolist(), color),
                            use_container_width=True, config={'displayModeBar': False},
                            key=f'spark-{ind.key}')

footer('Los indicadores permiten monitorear la cobertura, distribución y características de la '
       'afiliación al Sistema General de Seguridad Social en Salud en el territorio.', ['bdua', 'supersalud'])
