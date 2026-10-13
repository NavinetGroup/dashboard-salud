# -*- coding: utf-8 -*-
"""Demográficos — localización territorial y caracterización poblacional."""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from charts import donut_gender, map_location
from data import load_geojson
from registry import DEMOGRAFICOS, ETNIAS, MODULES
from ui import card_grid, footer, fmt, module_header, _v

sel = st.session_state['sel']


def _pct(v: float) -> str:
    return f'{v:.1f}%'.replace('.', ',')


color = MODULES['demograficos'][1]
row = sel.entity_row

module_header('demograficos', 'Caracterización poblacional del territorio — proyecciones DANE '
              'y autorreconocimiento étnico-racial', sel)

card_grid('demograficos', DEMOGRAFICOS, row, sel.prev_entity)

st.markdown('#### Localización territorial')
c_map, c_info = st.columns([3, 2])
with c_map:
    st.plotly_chart(map_location(sel.df_dept, load_geojson(), str(sel.dept_code).zfill(2), color),
                    use_container_width=True)
with c_info:
    st.markdown(f'**{html.escape(" › ".join(["Colombia", sel.dept_name] + ([sel.mun_name] if sel.mun_name else [])))}**')
    if sel.use_mun:
        n_mun = len(sel.df_mun)
        share = (_v(row, 'pob_total') or 0) / (_v(sel.dept_row, 'pob_total') or 1) * 100
        st.markdown(f'{html.escape(sel.mun_name)} concentra el **{_pct(share)}** de la población de '
                    f'{html.escape(sel.dept_name)} ({n_mun} municipios).')
    else:
        share = (_v(row, 'pob_total') or 0) / (_v(sel.nat_row, 'pob_total') or 1) * 100
        st.markdown(f'{html.escape(sel.dept_name)} tiene **{len(sel.df_mun)} municipios** y el '
                    f'**{_pct(share)}** de la población del país.')
    st.caption('Mapa municipal (municipio y vecinos): pendiente de la cartografía DANE MGN.')

c_sex, c_eth = st.columns([2, 3])
with c_sex:
    st.markdown('#### Distribución por sexo')
    st.plotly_chart(donut_gender(row), use_container_width=True)

with c_eth:
    st.markdown('#### Pertenencia étnico-racial')
    total = _v(row, 'pob_etnico_total')
    data = [(lbl, _v(row, c) or 0, clr) for c, lbl, clr in ETNIAS]
    fig = go.Figure(go.Bar(
        x=[v / total * 100 if total else 0 for _, v, _ in data], y=[l for l, _, _ in data],
        orientation='h', marker_color=[c for _, _, c in data],
        text=[_pct(v / total * 100) if total else '' for _, v, _ in data],
        textposition='outside', hovertemplate='%{y}: %{x:.1f}%<extra></extra>'))
    fig.update_layout(height=300, margin={'t': 10, 'b': 10, 'l': 10, 'r': 40}, plot_bgcolor='white',
                      xaxis={'visible': False}, yaxis={'autorange': 'reversed'})
    st.plotly_chart(fig, use_container_width=True)

st.markdown('#### Composición étnica')
tbl = pd.DataFrame([{
    'Grupo': lbl,
    'Población': fmt(DEMOGRAFICOS[2], _v(row, c)),
    '% sobre el total': _pct((_v(row, c) or 0) / total * 100) if total else 'N/D',
} for c, lbl, _ in ETNIAS])
st.dataframe(tbl, hide_index=True, use_container_width=True)

footer('La información corresponde a proyecciones poblacionales del DANE y al autorreconocimiento '
       'étnico-racial según el Censo Nacional (serie de proyecciones étnicas).', ['dane'])
