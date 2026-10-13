# -*- coding: utf-8 -*-
"""Prestación de servicios — oferta y capacidad de la red de prestadores (FCT)."""

import streamlit as st

from charts import donut_ips
from registry import CAPACIDAD, PRESTACION, Indicator
from ui import card_grid, footer, kpi_card, module_header, pending_card, _v

sel = st.session_state['sel']
row = sel.entity_row

module_header('prestacion', 'Oferta y capacidad de la red de prestadores', sel)

total = _v(row, 'ips_total')
notes = {ind.key: f'{_v(row, ind.col) / total * 100:.1f}% del total'.replace('.', ',')
         for ind in PRESTACION[1:] if total and _v(row, ind.col) is not None}
notes['ips_total'] = 'IPS habilitadas (REPS)'
card_grid('prestacion', PRESTACION, row, None, per_row=4, notes=notes)

st.markdown('#### Capacidad instalada')
card_grid('prestacion', CAPACIDAD, row, None, per_row=5)
st.caption('Capacidad reportada por las IPS habilitadas en el REPS. UCI pediátricas no incluye '
           'cuidado intensivo neonatal.')

c_interv, c_estado, c_red = st.columns([1, 1, 2])
with c_interv:
    kpi_card('prestacion', Indicator('ips_interv', 'IPS intervenidas por la Supersalud',
                                     'ips_intervenidas', 'IPS', icon='gpp_maybe', trend=''),
             sel.dept_row, None, f'Departamento de {sel.dept_name}' if sel.use_mun else '')
with c_estado:
    pending_card('prestacion', Indicator(
        'estado_interv', 'Estado de las intervenciones', None, icon='donut_large',
        pending='El listado público solo indica "Intervención forzosa": el estado '
                '(en intervención, programa, medida especial, finalizada) lo debe suministrar Supersalud.'))
with c_red:
    with st.container(border=True, key='card-prestacion-red'):
        st.markdown(':material/pie_chart: <span class="fct-label">Composición de la red de IPS</span>',
                    unsafe_allow_html=True)
        st.plotly_chart(donut_ips(row), use_container_width=True)

footer('Los indicadores permiten monitorear la oferta, capacidad instalada y estado de la red de '
       'prestadores de servicios de salud.', ['reps', 'supersalud'])
