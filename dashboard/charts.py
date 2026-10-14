# -*- coding: utf-8 -*-
"""Plotly figure builders for the dashboard."""


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

# Maps draw the DANE polygons on a plain background (plotly geo, fitted to the
# shapes): no tile server, so no API key and they work offline.
_GEO = dict(visible=False, bgcolor='rgba(0,0,0,0)', projection_type='mercator')


def _geo(geojson: dict, pad: float = 0.04) -> dict:
    """Geo layout framing the polygons by explicit lon/lat ranges. Plotly's
    fitbounds is computed at the first render width, before Streamlit narrows
    the column, which crops the map; fixed ranges re-fit on every resize."""
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)
    for f in geojson['features']:
        walk(f['geometry']['coordinates'])
    dx, dy = (max(xs) - min(xs)) * pad + 0.01, (max(ys) - min(ys)) * pad + 0.01
    return {**_GEO, 'lonaxis_range': [min(xs) - dx, max(xs) + dx],
            'lataxis_range': [min(ys) - dy, max(ys) + dy]}

_ETHNIC_COLS = [
    ('pob_indigena',     'Indígena'),
    ('pob_negra_afro',   'Negro / Afro'),
    ('pob_gitana_rrom',  'Gitano / Rrom'),
    ('pob_raizal',       'Raizal'),
    ('pob_palenquera',   'Palenquera'),
    ('pob_ninguno',      'Sin pertenencia'),
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
    fig = px.choropleth(
        df, geojson=geojson, locations='dep_str', featureidkey='properties.DPTO',
        color=metric, color_continuous_scale='Blues', hover_name='departamento',
        hover_data={metric: True, 'dep_str': False}, labels={metric: label or metric},
        title=title_txt, height=500)
    fig.update_traces(marker_line_width=0.6, marker_line_color='white')
    fig.update_geos(**_geo(geojson))
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


def bar_violence(row: pd.Series, nat: pd.Series | None = None, label: str = '',
                 title: str = 'Violencia por sub-tipo (tasa por 100.000 hab.)') -> go.Figure:
    """Sub-type rates per 100k for the entity, next to the national rate.

    The total of notified cases is a count, not a rate, so it is shown in the
    panel beside the chart rather than on this axis.
    """
    cats = [
        ('violencia_fisica',      'Física'),
        ('violencia_psicologica', 'Psicológica'),
        ('negligencia_abandono',  'Negligencia / abandono'),
        ('violencia_sexual',      'Sexual'),
    ]
    names = [lbl for _, lbl in cats]
    fig = go.Figure()
    fig.add_bar(name=label or 'Entidad', x=names,
                y=[_n(row.get(col)) for col, _ in cats], marker_color='#EF5350',
                text=[f'{_n(row.get(col)):,.1f}' if not _is_null(row.get(col)) else ''
                      for col, _ in cats],
                textposition='outside')
    if nat is not None and not nat.empty:
        fig.add_bar(name='Nacional', x=names,
                    y=[_n(nat.get(col)) for col, _ in cats], marker_color='#B0BEC5',
                    text=[f'{_n(nat.get(col)):,.1f}' if not _is_null(nat.get(col)) else ''
                          for col, _ in cats],
                    textposition='outside')
    fig.update_layout(title=title, yaxis_title='Tasa por 100.000 hab.', barmode='group',
                      height=340, margin={'t': 50, 'b': 10, 'l': 10, 'r': 10},
                      plot_bgcolor='white', yaxis={'gridcolor': '#F0F0F0'},
                      legend={'orientation': 'h', 'y': -0.15})
    return fig


# ── FCT design ────────────────────────────────────────────────────────────────

def map_location(df_dept: pd.DataFrame, geojson: dict, dep_str: str,
                 color: str = '#26A69A') -> go.Figure:
    """Colombia with the selected department highlighted (Localización territorial)."""
    d = df_dept[['departamento', 'dep_str']].copy()
    d['sel'] = (d['dep_str'] == dep_str).astype(int)
    fig = go.Figure(go.Choropleth(
        geojson=geojson, locations=d['dep_str'], z=d['sel'], featureidkey='properties.DPTO',
        colorscale=[[0, '#D7EDEA'], [1, color]], zmin=0, zmax=1, showscale=False,
        marker_line_width=0.6, marker_line_color='white',
        text=d['departamento'], hovertemplate='%{text}<extra></extra>'))
    fig.update_geos(**_geo(geojson))
    fig.update_layout(margin={'r': 0, 't': 0, 'l': 0, 'b': 0}, height=420,
                      paper_bgcolor='rgba(0,0,0,0)')
    return fig


def map_municipios(geojson: dict, names: dict[str, str], mun_str: str | None,
                   color: str = '#26A69A', height: int = 420, labels: bool = False) -> go.Figure:
    """A department's municipalities, the selected one highlighted (Localización
    municipal). names: 5-digit DIVIPOLA → municipality name, for the hover.
    labels=True writes each name at the centre of its bounding box (the
    close-up "municipio y alrededores" map, as in the mockup)."""
    ids = [f['id'] for f in geojson['features']]
    fig = go.Figure(go.Choropleth(
        geojson=geojson, locations=ids, z=[1 if i == mun_str else 0 for i in ids],
        featureidkey='id', colorscale=[[0, '#D7EDEA'], [1, color]], zmin=0, zmax=1,
        showscale=False, marker_line_width=0.5, marker_line_color='white',
        text=[names.get(i) or f['properties'].get('nombre', i).title()
              for i, f in zip(ids, geojson['features'])],
        hovertemplate='%{text}<extra></extra>'))
    if labels:
        feats = [f for f in geojson['features'] if 'bbox' in f]
        fig.add_trace(go.Scattergeo(
            lon=[(f['bbox'][0] + f['bbox'][2]) / 2 for f in feats],
            lat=[(f['bbox'][1] + f['bbox'][3]) / 2 for f in feats],
            text=[names.get(f['id']) or f['properties'].get('nombre', '').title() for f in feats],
            mode='text', hoverinfo='skip', showlegend=False,
            textfont={'size': [13 if f['id'] == mun_str else 10 for f in feats],
                      'color': ['white' if f['id'] == mun_str else '#37474F' for f in feats]}))
    fig.update_geos(**_geo(geojson))
    fig.update_layout(margin={'r': 0, 't': 0, 'l': 0, 'b': 0}, height=height,
                      paper_bgcolor='rgba(0,0,0,0)')
    return fig


def ring_pct(value: float | None, color: str = '#1E88E5', label: str = '') -> go.Figure:
    """Coverage ring: share filled, value in the centre (FCT Aseguramiento)."""
    v = max(0.0, min(100.0, _n(value)))
    fig = go.Figure(go.Pie(values=[v, 100 - v], hole=0.78, sort=False, direction='clockwise',
                           marker={'colors': [color, '#E3E8EC']}, textinfo='none',
                           hoverinfo='skip'))
    txt = 'N/D' if _is_null(value) else f'{v:,.1f}%'.replace('.', ',')
    fig.update_layout(showlegend=False, height=230, margin={'t': 10, 'b': 10, 'l': 10, 'r': 10},
                      annotations=[{'text': f'<b>{txt}</b><br><span style="font-size:11px">{label}</span>',
                                    'showarrow': False, 'font': {'size': 26, 'color': color}}])
    return fig


def sparkline(x: list, y: list, color: str = '#26A69A') -> go.Figure:
    fig = go.Figure(go.Scatter(x=x, y=y, mode='lines+markers', line={'color': color, 'width': 2},
                               marker={'size': 4}, fill='tozeroy',
                               fillcolor='rgba(38,166,154,0.10)', hovertemplate='%{x}: %{y:,.0f}<extra></extra>'))
    fig.update_layout(height=70, margin={'t': 0, 'b': 0, 'l': 0, 'r': 0}, showlegend=False,
                      xaxis={'visible': False}, yaxis={'visible': False}, plot_bgcolor='white')
    return fig


def pyramid_regimen(df: pd.DataFrame) -> go.Figure:
    """Affiliated-population pyramid: subsidised to the left, contributory to the
    right (FCT Aseguramiento), one bar per age group, split by sex."""
    fig = go.Figure()
    if df.empty:
        return fig
    ages = (df[['grupo_edad', 'orden_edad']].drop_duplicates().sort_values('orden_edad')['grupo_edad'].tolist())
    styles = {('subsidiado', 'Femenino'): '#1E88E5', ('subsidiado', 'Masculino'): '#64B5F6',
              ('contributivo', 'Femenino'): '#26A69A', ('contributivo', 'Masculino'): '#80CBC4'}
    for (reg, sexo), color in styles.items():
        d = df[(df['regimen'] == reg) & (df['sexo'] == sexo)].set_index('grupo_edad').reindex(ages)
        vals = d['afiliados'].fillna(0)
        fig.add_bar(y=ages, x=-vals if reg == 'subsidiado' else vals, orientation='h',
                    name=f'{reg.title()} — {sexo.lower()}', marker_color=color,
                    customdata=vals, hovertemplate='%{y}: %{customdata:,.0f}<extra>%{fullData.name}</extra>')
    m = df.groupby(['regimen', 'grupo_edad'])['afiliados'].sum().max()
    ticks = [-m, -m / 2, 0, m / 2, m]
    fig.update_layout(barmode='relative', height=360, bargap=0.12, plot_bgcolor='white',
                      margin={'t': 10, 'b': 10, 'l': 10, 'r': 10},
                      legend={'orientation': 'h', 'y': -0.12, 'font': {'size': 11}},
                      # symmetric around 0, so the two regimes read as one pyramid
                      xaxis={'range': [-m * 1.08, m * 1.08], 'tickvals': ticks,
                             'ticktext': [f'{abs(t):,.0f}'.replace(',', '.') for t in ticks],
                             'gridcolor': '#F0F0F0', 'zeroline': True, 'zerolinecolor': '#90A4AE'},
                      annotations=[{'text': '◄ Subsidiado', 'x': 0.02, 'y': 1.04, 'xref': 'paper',
                                    'yref': 'paper', 'showarrow': False, 'font': {'color': '#1E88E5'}},
                                   {'text': 'Contributivo ►', 'x': 0.98, 'y': 1.04, 'xref': 'paper',
                                    'yref': 'paper', 'showarrow': False, 'font': {'color': '#26A69A'}}])
    return fig
