# -*- coding: utf-8 -*-
"""Demográficos — localización territorial y caracterización poblacional."""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from charts import donut_gender, map_location, map_municipios
from data import load_geojson, load_geojson_mpios, load_geojson_vecinos
from registry import DEMOGRAFICOS, ETNIAS, MODULES
from ui import card_grid, footer, fmt, module_header, share_note, _v

sel = st.session_state['sel']


def _pct(v: float) -> str:
    return f'{v:.1f}%'.replace('.', ',')


color = MODULES['demograficos'][1]
row = sel.entity_row

module_header('demograficos', 'Caracterización poblacional del territorio — proyecciones DANE '
              'y autorreconocimiento étnico-racial', sel)

card_grid('demograficos', DEMOGRAFICOS, row, sel.prev_entity,
          notes={i.key: share_note(i, row) for i in DEMOGRAFICOS})

st.markdown('#### Localización territorial')
# Drill-down (FCT): Colombia → department → municipality and its surroundings
mun_str = str(int(sel.mun_code)).zfill(5) if sel.use_mun and sel.mun_code else None
names = {str(int(c)).zfill(5): n for c, n in zip(sel.df_mun['geo_mun_codigo'], sel.df_mun['municipio'])} \
    if 'geo_mun_codigo' in sel.df_mun else {}
vecinos = load_geojson_vecinos(sel.mun_code) if mun_str else None
if vecinos and vecinos['features']:
    c_map, c_mun, c_vec = st.columns(3)
else:
    c_map, c_mun = st.columns(2)
with c_map:
    st.caption('Colombia')
    st.plotly_chart(map_location(sel.df_dept, load_geojson(), str(sel.dept_code).zfill(2), color),
                    use_container_width=True)
with c_mun:
    st.caption(f'{sel.dept_name}: municipios' + (f' · {sel.mun_name} resaltado' if sel.use_mun else ''))
    st.plotly_chart(map_municipios(load_geojson_mpios(sel.dept_code), names, mun_str, color),
                    use_container_width=True)
if vecinos and vecinos['features']:
    with c_vec:
        st.caption(f'{sel.mun_name} y alrededores')
        st.plotly_chart(map_municipios(vecinos, names, mun_str, color, labels=True), use_container_width=True)
elif mun_str:
    st.caption(f'{sel.mun_name}: sin polígono en la cartografía DANE MGN 2025.')
with st.container():
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
    st.caption('Cartografía: DANE, Marco Geoestadístico Nacional 2025 (simplificado).')

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
