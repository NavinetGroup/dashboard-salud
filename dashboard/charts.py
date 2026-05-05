# -*- coding: utf-8 -*-
"""Plotly figure builders for the dashboard."""

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _n(val, default: float = 0.0) -> float:
    """Return val as float, or default if None/NaN/NAType."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _is_null(v) -> bool:
    """True for None, float NaN, pd.NA, numpy NaN, or any NA-like."""
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False

_MAPBOX_STYLE = 'carto-positron'
_MAP_CENTER = {'lat': 4.0, 'lon': -74.0}
_MAP_ZOOM = 4.3

_ETHNIC_COLS = [
    ('pob_indigena',     'Indígena'),
    ('pob_negra_afro',   'Negro / Afro'),
    ('pob_gitana_rrom',  'Gitano / Rrom'),
    ('pob_raizal',       'Raizal'),
    ('pob_palenquera',   'Palenquera'),
    ('pob_ninguno',      'Sin pertenencia'),
]

_INS_ROWS = [
    ('razon_mortalidad_materna',       'Mort. materna',            'x100k NV'),
    ('incidencia_sifilis_congenita',   'Sífilis congénita',        'x100k NV'),
    ('prevalencia_desnutricion_aguda', 'Desnutrición aguda',       'x100k <5'),
    ('tasa_mortalidad_menores5_dnt',   'Mort. <5 desnutrición',    'x100k <5'),
    ('tasa_mortalidad_menores5_ira',   'Mort. <5 IRA',             'x100k <5'),
    ('tasa_mortalidad_menores5_eda',   'Mort. <5 EDA',             'x100k <5'),
    ('incidencia_dengue_x100k',        'Dengue',                   'x100k hab'),
    ('tasa_intento_suicidio',          'Intento suicidio',         'x100k hab'),
    ('violencia_genero_intrafamiliar', 'Violencia género/intrafam','casos'),
    ('violencia_fisica',               'Violencia física',         'casos'),
    ('violencia_psicologica',          'Violencia psicológica',    'casos'),
    ('negligencia_abandono',           'Negligencia/abandono',     'casos'),
    ('violencia_sexual',               'Violencia sexual',         'casos'),
]


def gauge_irca(value: float | None, risk_level: str = '',
              title: str = 'IRCA promedio') -> go.Figure:
    """Gauge chart for IRCA (0–100 risk scale with colour zones)."""
    v = _n(value)
    # SIVICAP risk thresholds
    if v <= 5:
        bar_color = '#2E7D32'
    elif v <= 14:
        bar_color = '#558B2F'
    elif v <= 35:
        bar_color = '#F9A825'
    elif v <= 80:
        bar_color = '#E64A19'
    else:
        bar_color = '#B71C1C'

    risk_label = risk_level or (
        'Sin riesgo' if v <= 5 else
        'Bajo' if v <= 14 else
        'Medio' if v <= 35 else
        'Alto' if v <= 80 else
        'Inviable sanitariamente'
    )

    fig = go.Figure(go.Indicator(
        mode='gauge+number',
        value=v,
        number={'suffix': ' pts', 'font': {'size': 30, 'color': bar_color}},
        title={'text': f'{title}<br><span style="font-size:13px;color:{bar_color}">{risk_label}</span>',
               'font': {'size': 15}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1,
                     'tickvals': [0, 5, 14, 35, 80, 100],
                     'ticktext': ['0', '5', '14', '35', '80', '100']},
            'bar': {'color': bar_color, 'thickness': 0.28},
            'bgcolor': 'white',
            'borderwidth': 0,
            'steps': [
                {'range': [0,  5],   'color': '#E8F5E9'},
                {'range': [5,  14],  'color': '#DCEDC8'},
                {'range': [14, 35],  'color': '#FFF9C4'},
                {'range': [35, 80],  'color': '#FFE0B2'},
                {'range': [80, 100], 'color': '#FFCDD2'},
            ],
        },
    ))
    fig.update_layout(height=290, margin={'t': 80, 'b': 10, 'l': 30, 'r': 30},
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def gauge_pct(value: float | None, title: str = 'Cobertura') -> go.Figure:
    """Gauge chart for a 0–100 % metric (e.g., insurance coverage)."""
    v = _n(value)
    if v >= 90:
        bar_color, label = '#00897B', 'Optimo'
    elif v >= 75:
        bar_color, label = '#43A047', 'Bueno'
    elif v >= 60:
        bar_color, label = '#FDD835', 'Regular'
    else:
        bar_color, label = '#E53935', 'Critico'

    fig = go.Figure(go.Indicator(
        mode='gauge+number',
        value=v,
        number={'suffix': '%', 'font': {'size': 30, 'color': bar_color}},
        title={'text': f'{title}<br><span style="font-size:13px;color:{bar_color}">{label}</span>',
               'font': {'size': 15}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': bar_color, 'thickness': 0.28},
            'bgcolor': 'white',
            'borderwidth': 0,
            'steps': [
                {'range': [0,  60], 'color': '#FFCDD2'},
                {'range': [60, 75], 'color': '#FFF9C4'},
                {'range': [75, 90], 'color': '#DCEDC8'},
                {'range': [90, 100],'color': '#E8F5E9'},
            ],
        },
    ))
    fig.update_layout(height=290, margin={'t': 80, 'b': 10, 'l': 30, 'r': 30},
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def choropleth_dept(df: pd.DataFrame, metric: str, geojson: dict,
                    label: str = '', unit: str = '') -> go.Figure:
    title_txt = f'{label} ({unit})' if unit else label
    fig = px.choropleth_mapbox(
        df,
        geojson=geojson,
        locations='dep_str',
        featureidkey='properties.DPTO',
        color=metric,
        color_continuous_scale='Blues',
        mapbox_style=_MAPBOX_STYLE,
        zoom=_MAP_ZOOM,
        center=_MAP_CENTER,
        opacity=0.75,
        hover_name='departamento',
        hover_data={metric: True, 'dep_str': False},
        labels={metric: label or metric},
        title=title_txt,
        height=500,
    )
    fig.update_layout(margin={'r': 0, 't': 40, 'l': 0, 'b': 0},
                      coloraxis_colorbar={'title': unit or ''})
    return fig


def _donut(vals: list, labels: list, colors: list,
           title: str, center_label: str = '') -> go.Figure:
    """Shared donut builder: clean slices, percent labels outside, legend below."""
    total = sum(v for v in vals if v)
    center_text = center_label or (f'{total:,.0f}' if total else '')

    fig = go.Figure(go.Pie(
        values=vals,
        labels=labels,
        hole=0.60,
        marker={'colors': colors, 'line': {'color': 'white', 'width': 3}},
        textposition='outside',
        textinfo='percent',
        textfont={'size': 13, 'color': '#333'},
        hovertemplate='<b>%{label}</b><br>%{value:,.0f}<br>%{percent}<extra></extra>',
        pull=[0.03] * len(vals),
    ))

    # Centre annotation: label + value
    fig.add_annotation(
        text=f'<b style="font-size:15px">{center_text}</b>',
        x=0.5, y=0.5, showarrow=False,
        font={'size': 15, 'color': '#1A237E'},
        xanchor='center', yanchor='middle',
    )

    fig.update_layout(
        title={'text': title, 'font': {'size': 13}, 'x': 0.5, 'xanchor': 'center'},
        showlegend=True,
        legend={
            'orientation': 'h',
            'x': 0.5, 'xanchor': 'center',
            'y': -0.12,
            'font': {'size': 11},
        },
        margin={'t': 45, 'b': 30, 'l': 20, 'r': 20},
        height=290,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def donut_ips(row: pd.Series) -> go.Figure:
    vals   = [_n(row.get('ips_publica')), _n(row.get('ips_privada')), _n(row.get('ips_mixta'))]
    labels = ['Pública', 'Privada', 'Mixta']
    colors = ['#26A69A', '#42A5F5', '#FFA726']
    total  = int(sum(vals))
    return _donut(vals, labels, colors, 'Tipo de IPS', f'{total:,}\nIPS')


def donut_afil(row: pd.Series) -> go.Figure:
    vals   = [_n(row.get('afiliados_subsidiado')), _n(row.get('afiliados_contributivo'))]
    labels = ['Subsidiado', 'Contributivo']
    colors = ['#5C6BC0', '#26C6DA']
    total  = int(sum(vals))
    return _donut(vals, labels, colors, 'Régimen de afiliación',
                  f'{total:,}\nafiliados')


def donut_gender(row: pd.Series) -> go.Figure:
    vals   = [_n(row.get('pob_hombres')), _n(row.get('pob_mujeres'))]
    labels = ['Hombres', 'Mujeres']
    colors = ['#42A5F5', '#EC407A']
    total  = int(sum(vals))
    return _donut(vals, labels, colors, 'Distribución por sexo',
                  f'{total:,}\nhabitantes')


def bar_ethnic(row: pd.Series, title: str = 'Pertenencia étnica') -> go.Figure:
    names = [lbl for _, lbl in _ETHNIC_COLS]
    vals = [_n(row.get(col)) for col, _ in _ETHNIC_COLS]
    fig = px.bar(x=names, y=vals,
                 labels={'x': '', 'y': 'Personas'},
                 color=names,
                 color_discrete_sequence=px.colors.qualitative.Safe,
                 title=title)
    fig.update_layout(showlegend=False, height=300,
                      margin={'t': 50, 'b': 10, 'l': 10, 'r': 10})
    return fig


def bar_muns_top(df_muns: pd.DataFrame, metric: str, label: str,
                 n: int = 10) -> go.Figure:
    top = (df_muns[['municipio', metric]]
           .dropna(subset=[metric])
           .nlargest(n, metric))
    fig = px.bar(top, x=metric, y='municipio', orientation='h',
                 labels={metric: label, 'municipio': ''},
                 title=f'Top {n} municipios — {label}',
                 color=metric, color_continuous_scale='Blues')
    fig.update_layout(showlegend=False, yaxis={'categoryorder': 'total ascending'},
                      height=320, margin={'t': 50, 'b': 10, 'l': 10, 'r': 10})
    fig.update_coloraxes(showscale=False)
    return fig


def bar_comparison(labels: list, values: list, unit: str = '',
                   title: str = '', entity_idx: int = -1) -> go.Figure:
    """Vertical bar comparing an entity (highlighted) against reference averages."""
    _ENTITY_COLOR = '#1565C0'
    _REF_COLOR    = '#BBDEFB'
    _NULL_COLOR   = '#EEEEEE'

    colors, clean_vals, texts = [], [], []
    for i, v in enumerate(values):
        null = _is_null(v)
        colors.append(_NULL_COLOR if null else (_ENTITY_COLOR if i == entity_idx else _REF_COLOR))
        clean_vals.append(0 if null else float(v))
        texts.append('N/D' if null else f'{float(v):,.1f}')

    fig = go.Figure(go.Bar(
        x=labels, y=clean_vals,
        marker_color=colors,
        marker_line_width=0,
        text=texts,
        textposition='outside',
        textfont={'size': 13, 'color': '#333'},
    ))
    fig.update_layout(
        title={'text': title, 'font': {'size': 14}, 'x': 0, 'xanchor': 'left'},
        yaxis_title=unit,
        height=320,
        margin={'t': 55, 'b': 10, 'l': 10, 'r': 10},
        showlegend=False,
        plot_bgcolor='white',
        paper_bgcolor='rgba(0,0,0,0)',
        yaxis={'gridcolor': '#F5F5F5', 'zeroline': False, 'showline': False},
        xaxis={'showline': False},
        bargap=0.35,
    )
    return fig


def bar_dift18_scores(indicators: list[tuple[str, float | None]],
                      title: str = 'Desempeño ET 2024') -> go.Figure:
    """Horizontal bar chart of DIFT18 puntaje values (1–4 scale)."""
    _colors = {1: '#EF5350', 2: '#FFA726', 3: '#66BB6A', 4: '#26A69A'}
    names, vals, colors, texts = [], [], [], []
    for lbl, v in indicators:
        if _is_null(v):
            continue
        pts = max(1, min(4, round(float(v))))
        names.append(lbl)
        vals.append(pts)
        colors.append(_colors.get(pts, '#90CAF9'))
        _lbl_map = {1: 'Bajo', 2: 'En proceso', 3: 'Satisfactorio', 4: 'Óptimo'}
        texts.append(f'{pts} — {_lbl_map[pts]}')

    if not names:
        fig = go.Figure()
        fig.update_layout(title=title, height=200,
                          annotations=[{'text': 'Sin datos', 'xref': 'paper',
                                        'yref': 'paper', 'x': .5, 'y': .5, 'showarrow': False}])
        return fig

    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation='h',
        marker_color=colors, text=texts, textposition='outside',
    ))
    fig.update_layout(
        title=title, xaxis=dict(range=[0, 4.8], tickvals=[1, 2, 3, 4],
                                ticktext=['1\nBajo', '2\nEn proceso', '3\nSatisfactorio', '4\nÓptimo']),
        yaxis={'categoryorder': 'array', 'categoryarray': list(reversed(names))},
        height=max(200, len(names) * 38),
        margin={'t': 50, 'b': 10, 'l': 10, 'r': 10},
        plot_bgcolor='white',
    )
    return fig


def bar_violence(row: pd.Series, title: str = 'Violencia de género e intrafamiliar') -> go.Figure:
    """Grouped bar of violence sub-types."""
    cats = [
        ('violencia_fisica',               'Violencia física'),
        ('violencia_psicologica',          'Violencia psicológica'),
        ('negligencia_abandono',           'Negligencia / abandono'),
        ('violencia_sexual',               'Violencia sexual'),
        ('violencia_genero_intrafamiliar', 'Total género/intrafamiliar'),
    ]
    names = [lbl for _, lbl in cats]
    vals  = [_n(row.get(col)) for col, _ in cats]
    colors = ['#EF9A9A', '#F48FB1', '#CE93D8', '#80DEEA', '#EF5350']
    fig = go.Figure(go.Bar(x=names, y=vals, marker_color=colors,
                           text=[f'{v:,.0f}' if v else '' for v in vals],
                           textposition='outside'))
    fig.update_layout(title=title, yaxis_title='Casos', height=340,
                      margin={'t': 50, 'b': 10, 'l': 10, 'r': 10},
                      plot_bgcolor='white', yaxis={'gridcolor': '#F0F0F0'})
    return fig


def bar_ins(row: pd.Series, title: str = 'Indicadores de salud pública') -> go.Figure:
    labels, vals, units = [], [], []
    for col, lbl, unit in _INS_ROWS:
        v = row.get(col)
        if v is not None and not pd.isna(v) and v > 0:
            labels.append(f'{lbl}\n({unit})')
            vals.append(float(v))
            units.append(unit)
    if not vals:
        fig = go.Figure()
        fig.update_layout(title=title,
                          annotations=[{'text': 'Sin datos disponibles',
                                        'xref': 'paper', 'yref': 'paper',
                                        'x': 0.5, 'y': 0.5, 'showarrow': False}],
                          height=250)
        return fig
    fig = px.bar(x=vals, y=labels, orientation='h',
                 labels={'x': 'Valor', 'y': ''},
                 title=title,
                 color=vals, color_continuous_scale='Oranges')
    fig.update_layout(yaxis={'categoryorder': 'total ascending'},
                      height=max(250, len(vals) * 45),
                      margin={'t': 50, 'b': 10, 'l': 10, 'r': 10},
                      showlegend=False)
    fig.update_coloraxes(showscale=False)
    return fig
