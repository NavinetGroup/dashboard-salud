# -*- coding: utf-8 -*-
"""Demográficos — localización territorial y caracterización poblacional."""

import html

import plotly.graph_objects as go
import streamlit as st

from charts import donut_gender, map_location, map_municipios
from data import load_geojson, load_geojson_mpios, load_geojson_vecinos
from registry import DEMOGRAFICOS, ETNIAS, MODULES
from ui import card_grid, chart, footer, fmt, module_header, panel, share_note, _v

sel = st.session_state['sel']


def _pct(v: float) -> str:
    return f'{v:.1f}%'.replace('.', ',')


color = MODULES['demograficos'][1]
row = sel.entity_row

module_header('demograficos', 'Caracterización poblacional del territorio — proyecciones DANE '
              'y autorreconocimiento étnico-racial', sel)

card_grid('demograficos', DEMOGRAFICOS, row, sel.prev_entity,
          notes={i.key: share_note(i, row) for i in DEMOGRAFICOS})

# Drill-down (FCT): Colombia → department → municipality and its surroundings
mun_str = str(int(sel.mun_code)).zfill(5) if sel.use_mun and sel.mun_code else None
names = {str(int(c)).zfill(5): n for c, n in zip(sel.df_mun['geo_mun_codigo'], sel.df_mun['municipio'])}     if 'geo_mun_codigo' in sel.df_mun else {}
vecinos = load_geojson_vecinos(sel.mun_code) if mun_str else None
if sel.use_mun:
    share = (_v(row, 'pob_total') or 0) / (_v(sel.dept_row, 'pob_total') or 1) * 100
    resumen = (f'{sel.mun_name} concentra el {_pct(share)} de la población de {sel.dept_name} '
               f'({len(sel.df_mun)} municipios).')
else:
    share = (_v(row, 'pob_total') or 0) / (_v(sel.nat_row, 'pob_total') or 1) * 100
    resumen = (f'{sel.dept_name} tiene {len(sel.df_mun)} municipios y el {_pct(share)} de la población '
               'del país.')
with panel('demograficos', 'Localización territorial · ' + " › ".join(["Colombia", sel.dept_name] + ([sel.mun_name] if sel.mun_name else [])), 'location_on',
           resumen + ' Cartografía: DANE, Marco Geoestadístico Nacional 2025.'):
    has_vec = bool(vecinos and vecinos['features'])
    cols = st.columns(3 if has_vec else 2)
    with cols[0]:
        st.caption('Colombia')
        chart(map_location(sel.df_dept, load_geojson(), str(sel.dept_code).zfill(2), color), key='map-col')
    with cols[1]:
        st.caption(f'{sel.dept_name}: municipios' + (f' · {sel.mun_name} resaltado' if sel.use_mun else ''))
        chart(map_municipios(load_geojson_mpios(sel.dept_code), names, mun_str, color), key='map-dep')
    if has_vec:
        with cols[2]:
            st.caption(f'{sel.mun_name} y alrededores')
            chart(map_municipios(vecinos, names, mun_str, color, labels=True), key='map-vec')
    elif mun_str:
        st.caption(f'{sel.mun_name}: sin polígono en la cartografía DANE MGN 2025.')

total = _v(row, 'pob_etnico_total')
c_sex, c_eth = st.columns([2, 3])
with c_sex, panel('demograficos', 'Distribución por sexo', 'wc'):
    chart(donut_gender(row, color, height=300), key='donut-sexo')
with c_eth, panel('demograficos', 'Pertenencia étnico-racial', 'diversity_3',
                  'Participación sobre la población total'):
    data = [(lbl, _v(row, c) or 0, clr) for c, lbl, clr in ETNIAS]
    shares = [v / total * 100 if total else 0 for _, v, _ in data]
    fig = go.Figure(go.Bar(
        x=shares, y=[l for l, _, _ in data], orientation='h', marker_color=[c for _, _, c in data],
        text=[_pct(s) if total else '' for s in shares], textposition='outside', cliponaxis=False,
        textfont={'size': 13, 'color': '#37474F'}, hovertemplate='%{y}: %{x:.1f} %<extra></extra>'))
    fig.update_layout(height=280, margin={'t': 6, 'b': 6, 'l': 6, 'r': 56}, bargap=0.35,
                      plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                      xaxis={'visible': False, 'range': [0, max(shares + [1]) * 1.15]},
                      yaxis={'autorange': 'reversed', 'tickfont': {'size': 12.5, 'color': '#37474F'}})
    chart(fig, key='bar-etnia')

_DESC = {
    'pob_indigena': 'Población que se autorreconoce como indígena',
    'pob_gitana_rrom': 'Población que se autorreconoce como gitana o Rrom',
    'pob_raizal': 'Población raizal del Archipiélago de San Andrés, Providencia y Santa Catalina',
    'pob_palenquera': 'Población que se autorreconoce como palenquera de San Basilio',
    'pob_negra_afro': 'Población negra, mulata, afrodescendiente o afrocolombiana',
    'pob_ninguno': 'Población que no se autorreconoce en ningún grupo étnico-racial',
}
with panel('demograficos', 'Composición étnica', 'groups'):
    rows_html = ''.join(
        f'<tr><td><span class="fct-chip" style="background:{clr}"></span><b>{html.escape(lbl)}</b></td>'
        f'<td style="color:#607D8B">{html.escape(_DESC.get(c, ""))}</td>'
        f'<td style="color:#37474F">{fmt(DEMOGRAFICOS[2], _v(row, c))}</td>'
        f'<td style="color:{clr if c != "pob_ninguno" else "#607D8B"}">'
        f'{_pct((_v(row, c) or 0) / total * 100) if total else "N/D"}</td></tr>'
        for c, lbl, clr in ETNIAS)
    st.markdown(f'<table class="fct-table">{rows_html}</table>', unsafe_allow_html=True)

footer('La información corresponde a proyecciones poblacionales del DANE y al autorreconocimiento '
       'étnico-racial según el Censo Nacional (serie de proyecciones étnicas).', ['dane'])
