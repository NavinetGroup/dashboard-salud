# -*- coding: utf-8 -*-
"""Prestación de servicios — oferta y capacidad de la red de prestadores (FCT)."""

import streamlit as st

from charts import donut_ips
from registry import CAPACIDAD, IPS_INTERV, PRESTACION, Indicator
from ui import CARD_H, card_grid, chart, footer, kpi_card, module_header, panel, pending_card, _v

sel = st.session_state['sel']
row = sel.entity_row

module_header('prestacion', 'Oferta y capacidad de la red de prestadores', sel)

total = _v(row, 'ips_total')
notes = {ind.key: f'{_v(row, ind.col) / total * 100:.1f}% del total'.replace('.', ',')
         for ind in PRESTACION[1:] if total and _v(row, ind.col) is not None}
notes['ips_total'] = 'IPS habilitadas (REPS)'
card_grid('prestacion', PRESTACION, row, None, per_row=4, notes=notes)

with panel('prestacion', 'Capacidad instalada', 'bed',
           'Reportada por las IPS habilitadas en el REPS. UCI pediátricas no incluye cuidado intensivo neonatal.'):
    card_grid('prestacion', CAPACIDAD, row, None, per_row=5)

c_interv, c_estado, c_red = st.columns([1, 1, 2])
with c_interv:
    kpi_card('prestacion', IPS_INTERV, sel.dept_row, None,
             f'Departamento de {sel.dept_name}' if sel.use_mun else '')
with c_estado:
    pending_card('prestacion', Indicator(
        'estado_interv', 'Estado de las intervenciones', None, icon='donut_large',
        pending='El listado público solo indica "Intervención forzosa": el estado '
                '(en intervención, programa, medida especial, finalizada) lo debe suministrar Supersalud.'))
with c_red:
    with panel('prestacion', 'Composición de la red de IPS', 'pie_chart'):
        chart(donut_ips(row, height=CARD_H - 60), key='donut-ips')

footer('Los indicadores permiten monitorear la oferta, capacidad instalada y estado de la red de '
       'prestadores de servicios de salud.', ['reps', 'supersalud'])
