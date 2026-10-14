# -*- coding: utf-8 -*-
"""Prestación de servicios — oferta y capacidad de la red de prestadores (FCT)."""

import html

import streamlit as st

from charts import donut_ips
from registry import CAPACIDAD, IPS_INTERV, MODULES, PRESTACION, Indicator
from ui import card_grid, chart, fmt, footer, kpi_card, module_header, panel, pending_card, _v

sel = st.session_state['sel']
row = sel.entity_row

module_header('prestacion', 'Oferta y capacidad de la red de prestadores', sel)

total = _v(row, 'ips_total')
notes = {ind.key: f'{_v(row, ind.col) / total * 100:.1f}% del total'.replace('.', ',')
         for ind in PRESTACION[1:] if total and _v(row, ind.col) is not None}
notes['ips_total'] = 'IPS habilitadas (REPS)'
card_grid('prestacion', PRESTACION, row, None, per_row=4, notes=notes, start=1)

color = MODULES['prestacion'][1]
c_cap, c_interv, c_estado = st.columns([2, 1, 1])
with c_cap, panel('prestacion', '5. Capacidad instalada', 'bed'):
    # mockup: big icon on the left, one row per resource on the right
    items = ''.join(
        f'<div class="it"><span class="ic" style="color:{color};background:{color}1F">{i.icon}</span>'
        f'<span class="lb">{html.escape(i.label)}</span>'
        f'<span class="vl" style="color:{color}">{fmt(i, _v(row, i.col))}</span></div>' for i in CAPACIDAD)
    st.markdown(f'<div class="fct-cap"><span class="big" style="color:{color};background:{color}14">'
                f'local_hotel</span><div class="ls">{items}</div></div>'
                '<div class="fct-panel-sub">Reportada por las IPS habilitadas en el REPS. UCI pediátricas '
                'no incluye cuidado intensivo neonatal.</div>', unsafe_allow_html=True)
with c_interv:
    kpi_card('prestacion', IPS_INTERV, sel.dept_row, None,
             f'Departamento de {sel.dept_name}' if sel.use_mun else 'Por departamento de la IPS', num=6)
with c_estado:
    pending_card('prestacion', Indicator(
        'estado_interv', 'Estado de las intervenciones', None, icon='donut_large',
        pending='El listado público solo indica "Intervención forzosa": el estado '
                '(en intervención, programa, medida especial, finalizada) lo debe suministrar Supersalud.'))
with panel('prestacion', 'Composición de la red de IPS', 'pie_chart'):
    chart(donut_ips(row, height=220), key='donut-ips')

footer('Los indicadores permiten monitorear la oferta, capacidad instalada y estado de la red de '
       'prestadores de servicios de salud.', ['reps', 'supersalud'])
