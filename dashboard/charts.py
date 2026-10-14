# -*- coding: utf-8 -*-
"""Plotly figure builders for the dashboard."""


import pandas as pd
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

def _donut(vals: list, labels: list, colors: list, center_value: str, center_label: str,
           height: int = 260) -> go.Figure:
    """Donut in the FCT style: no title (the panel has it), centre total, legend on
    the right reading '49,1 %  Hombres (1.234.567)'."""
    total = sum(v for v in vals if v) or 0
    names = [f'<b>{(v / total * 100 if total else 0):.1f} %</b>  {l} ({v:,.0f})'
             .replace(',', '§').replace('.', ',').replace('§', '.') for v, l in zip(vals, labels)]
    fig = go.Figure(go.Pie(
        values=vals, labels=names, hole=0.66, sort=False, direction='clockwise',
        marker={'colors': colors, 'line': {'color': 'white', 'width': 2}}, textinfo='none',
        hovertemplate='%{label}<extra></extra>'))
    fig.add_annotation(text=f'<b>{center_value}</b><br><span style="font-size:11px;color:#78909C">'
                            f'{center_label}</span>',
                       x=0.5, y=0.5, showarrow=False, font={'size': 17, 'color': '#263238'})
    fig.update_layout(showlegend=True, height=height, margin={'t': 6, 'b': 6, 'l': 6, 'r': 6},
                      legend={'orientation': 'v', 'x': 1.02, 'xanchor': 'left', 'y': 0.5, 'yanchor': 'middle',
                              'font': {'size': 13, 'color': '#37474F'}},
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def _thousands(v: float) -> str:
    return f'{v:,.0f}'.replace(',', '.')


def donut_ips(row: pd.Series, height: int = 260) -> go.Figure:
    """Network composition in the Prestación greens (mockup: públicas dark,
    privadas light, mixtas yellow)."""
    vals = [_n(row.get('ips_publica')), _n(row.get('ips_privada')), _n(row.get('ips_mixta'))]
    return _donut(vals, ['Públicas', 'Privadas', 'Mixtas'], ['#2E7D32', '#A5D6A7', '#FBC02D'],
                  _thousands(sum(vals)), 'IPS', height)


def donut_gender(row: pd.Series, color: str = '#26A69A', height: int = 280) -> go.Figure:
    """Sex split in the Demográficos teal (mockup: hombres dark, mujeres light)."""
    vals = [_n(row.get('pob_hombres')), _n(row.get('pob_mujeres'))]
    return _donut(vals, ['Hombres', 'Mujeres'], [color, '#A7DCD6'], _thousands(sum(vals)),
                  'habitantes', height)


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


def ring_pct(value: float | None, color: str = '#1E88E5', label: str = '', height: int = 230) -> go.Figure:
    """Coverage ring: share filled, value in the centre (FCT Aseguramiento)."""
    v = max(0.0, min(100.0, _n(value)))
    fig = go.Figure(go.Pie(values=[v, 100 - v], hole=0.78, sort=False, direction='clockwise',
                           marker={'colors': [color, '#E3E8EC']}, textinfo='none',
                           hoverinfo='skip'))
    txt = 'N/D' if _is_null(value) else f'{v:,.1f}%'.replace('.', ',')
    fig.update_layout(showlegend=False, height=height, margin={'t': 10, 'b': 10, 'l': 10, 'r': 10},
                      paper_bgcolor='rgba(0,0,0,0)',
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


def pyramid_regimen(df: pd.DataFrame, height: int = 360) -> go.Figure:
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
    fig.update_layout(barmode='relative', height=height, bargap=0.12, plot_bgcolor='rgba(0,0,0,0)',
                      paper_bgcolor='rgba(0,0,0,0)',
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
