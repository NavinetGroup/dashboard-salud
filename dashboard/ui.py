# -*- coding: utf-8 -*-
"""Visual building blocks for the FCT design: module header, KPI cards with a
trend vs. the same period of the previous year, "fuente pendiente" cards and
the source footer. Icons are Streamlit's bundled Material Symbols (work offline).
"""

import html
import re
from contextlib import contextmanager

import pandas as pd
import streamlit as st

from registry import MODULES, SRC, Indicator

_GOOD, _BAD, _FLAT = '#2E7D32', '#C62828', '#F9A825'
CARD_H = 226          # px: every KPI card, so cards in a row and across rows line up


_SIDEBAR_BG = 'linear-gradient(180deg, #0B5D5E 0%, #084A4B 100%)'
_NAV_EXTRA = {'detallado': '#546E7A'}   # pages outside MODULES: their chip colour


def _sidebar_css() -> str:
    """Dark Supersalud-teal sidebar (FCT mockup palette): each module link has an
    icon chip in its module colour and fills with it when active; the filters sit
    in a light panel. Pages are matched by their URL path (st.Page file name)."""
    chips = '\n'.join(
        f'[data-testid="stSidebarNavLink"][href$="/{slug}"] [data-testid="stIconMaterial"] '
        f'{{ background: {c}; }}\n'
        f'[data-testid="stSidebarNavLink"][href$="/{slug}"][aria-current="page"] '
        f'{{ background: {c} !important; }}'
        for slug, c in {**{k: v[1] for k, v in MODULES.items()}, **_NAV_EXTRA}.items())
    return f"""
[data-testid="stSidebar"] {{ background: {_SIDEBAR_BG}; }}
[data-testid="stSidebarHeader"] {{ margin: 10px 10px 4px 10px; padding: 8px 10px; background: #FFFFFF;
    border-radius: 12px; }}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {{ color: #0B5D5E; }}
[data-testid="stNavSectionHeader"], [data-testid="stNavSectionHeader"] * {{
    color: rgba(255,255,255,.62) !important; text-transform: uppercase; letter-spacing: .6px;
    font-size: 11px !important; font-weight: 700; }}
[data-testid="stSidebarNavSeparator"] {{ border-color: rgba(255,255,255,.18) !important; }}
[data-testid="stSidebarNavLink"] {{ border-radius: 10px; margin: 2px 0; padding: 4px 8px; }}
[data-testid="stSidebarNavLink"]:hover {{ background: rgba(255,255,255,.10) !important; }}
[data-testid="stSidebarNavLink"] span, [data-testid="stSidebarNavLink"] p {{
    color: rgba(255,255,255,.90) !important; font-weight: 600; }}
[data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] {{
    color: #FFFFFF !important; background: rgba(255,255,255,.16); border-radius: 8px;
    padding: 3px; font-size: 18px; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: rgba(255,255,255,.18) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,.18); }}
[data-testid="stSidebarNavLink"][aria-current="page"] span,
[data-testid="stSidebarNavLink"][aria-current="page"] p {{ color: #FFFFFF !important; font-weight: 800; }}
[data-testid="stSidebarNavLink"][aria-current="page"] [data-testid="stIconMaterial"] {{
    background: rgba(255,255,255,.22) !important; }}
{chips}
.st-key-filtros {{ background: #FFFFFF; border-radius: 14px; padding: 12px 12px 6px 12px;
    box-shadow: 0 2px 10px rgba(0,0,0,.15); }}
.st-key-filtros [data-testid="stWidgetLabel"] p {{ color: #0B5D5E !important; font-size: 11.5px;
    font-weight: 800; text-transform: uppercase; letter-spacing: .4px; }}
.st-key-filtros [data-baseweb="select"] > div {{ background: #F2F6F7; border-color: #D5E3E4;
    border-radius: 10px; }}
.fct-filtros-title {{ color: #0B5D5E; font-weight: 800; font-size: 13px; letter-spacing: .6px;
    display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }}
[data-testid="stSidebarUserContent"] [data-testid="stCaptionContainer"],
[data-testid="stSidebarUserContent"] [data-testid="stCaptionContainer"] * {{
    color: rgba(255,255,255,.78) !important; }}
.st-key-filtros [data-testid="stCaptionContainer"],
.st-key-filtros [data-testid="stCaptionContainer"] * {{ color: #546E7A !important; }}
"""


def inject_css() -> None:
    panels = '\n'.join(f'[class*="st-key-panel-{m}-"] {{ border-top-color: {c} !important; }}'
                         for m, (_, c, _) in MODULES.items())
    st.markdown(f"""
<style>
{_sidebar_css()}
/* ── KPI card: one fixed layout everywhere, so cards in a row line up ───────── */
.fct-card {{
    height: {CARD_H}px; display: flex; flex-direction: column; overflow: hidden;
    background: #FFFFFF; border-radius: 14px; border-top: 4px solid var(--c);
    box-shadow: 0 2px 10px rgba(0,0,0,.07); padding: 12px 14px 10px 14px; margin-bottom: 14px; }}
.fct-card.pending {{ background: #F5F7F8; border-top-color: #CFD8DC; box-shadow: none; }}
.fct-card-h {{ display: flex; gap: 6px; align-items: flex-start; min-height: 47px; }}
.fct-ico {{ font-family: 'Material Symbols Rounded'; font-size: 18px; line-height: 17px;
    color: var(--c, #546E7A); font-weight: normal; font-style: normal; letter-spacing: normal;
    text-transform: none; white-space: nowrap; -webkit-font-feature-settings: 'liga';
    font-feature-settings: 'liga'; -webkit-font-smoothing: antialiased; }}
.fct-label {{ font-size: 11.5px; font-weight: 700; color: #37474F; text-transform: uppercase;
    letter-spacing: .3px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 3;
    -webkit-box-orient: vertical; overflow: hidden; }}
.fct-card-v {{ margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.fct-value  {{ font-size: 30px; font-weight: 800; line-height: 1.1; color: var(--c); }}
.fct-value.nd {{ color: #B0BEC5; }}
.fct-value.small {{ font-size: 20px; }}
.fct-unit   {{ font-size: 12px; color: #78909C; margin-top: 1px; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; min-height: 16px; }}
.fct-trend  {{ font-size: 11.5px; margin-top: 6px; padding: 3px 8px; border-radius: 8px;
    background: #F5F7F8; max-width: 100%; align-self: flex-start; line-height: 1.3;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.fct-spark {{ margin-top: 4px; height: 30px; }}
.fct-card-f {{ margin-top: auto; font-size: 11px; color: #78909C; line-height: 1.35; }}
.fct-card-f div {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.fct-card-f .fct-period {{ -webkit-line-clamp: 1; color: #90A4AE; }}
/* ── panel: white titled box for charts and tables ─────────────────────────── */
[class*="st-key-panel-"] {{ background: #FFFFFF; border-radius: 16px; border-top: 4px solid #CFD8DC;
    box-shadow: 0 2px 10px rgba(0,0,0,.07); padding: 12px 16px 8px 16px; margin-bottom: 14px; }}
{panels}
.fct-panel-h {{ font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: .4px;
    display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }}
.fct-panel-h .fct-ico {{ color: inherit; }}
.fct-panel-sub {{ font-size: 12px; color: #78909C; margin: -2px 0 4px 0; }}
.fct-header {{ border-radius: 16px; padding: 18px 24px; color: white; margin-bottom: 14px; }}
.fct-header h1 {{ color: white; font-size: 30px; margin: 0; padding: 0; font-weight: 800; }}
.fct-header p  {{ color: rgba(255,255,255,.88); margin: 4px 0 0 0; font-size: 15px; }}
.fct-crumb  {{ font-size: 14px; color: rgba(255,255,255,.9); margin-top: 6px; }}
.fct-footer {{ background: #EEF5F5; border-radius: 12px; padding: 10px 16px; font-size: 12.5px;
               color: #455A64; margin-top: 16px; }}
.fct-table {{ width: 100%; border-collapse: separate; border-spacing: 0 6px; font-size: 13.5px; }}
.fct-table, .fct-table tr, .fct-table td {{ border: none !important; }}
.fct-table td {{ padding: 8px 10px; background: #F7FAFA; }}
.fct-table td:nth-child(3) {{ text-align: right; color: #37474F; }}
.fct-table td:first-child {{ border-radius: 10px 0 0 10px; }}
.fct-table td:last-child {{ border-radius: 0 10px 10px 0; text-align: right; font-weight: 800; }}
.fct-chip {{ display: inline-block; width: 12px; height: 12px; border-radius: 4px; margin-right: 8px;
    vertical-align: -1px; }}
</style>""", unsafe_allow_html=True)


def module_header(module: str, subtitle: str, sel) -> None:
    title, color, icon = MODULES[module]
    crumb = ' › '.join(['Colombia', sel.dept_name] + ([sel.mun_name] if sel.mun_name else []))
    st.markdown(
        f'<div class="fct-header" style="background:linear-gradient(90deg,{color},{color}CC)">'
        f'<h1>{html.escape(title.upper())}</h1><p>{html.escape(subtitle)}</p>'
        f'<div class="fct-crumb">{html.escape(crumb)} · {html.escape(sel.period_label)}</div></div>',
        unsafe_allow_html=True)


# ── values and trends ─────────────────────────────────────────────────────────

def _v(row: 'pd.Series | None', col: str | None):
    if row is None or col is None or col not in row.index:
        return None
    v = row[col]
    return None if v is None or pd.isna(v) else v


def fmt(ind: Indicator, v) -> str:
    if v is None:
        return 'N/D'
    s = f'{float(v):,.{ind.decimals}f}'
    # Spanish formatting: 1.234.567,8
    s = s.replace(',', '§').replace('.', ',').replace('§', '.')
    return s + ('%' if ind.unit == '%' else '')


def _same_period(period: str | None, prev_period: str | None) -> bool:
    """'2026 PE IX' vs '2025 PE IX' or 'AGOSTO 2026' vs 'AGOSTO 2025': equal once the
    year is removed. A municipality's latest IRCA can be March this year and June
    last year; comparing those would not be a year-on-year trend."""
    if not period or not prev_period:
        return True
    strip = lambda p: ' '.join(t for t in str(p).split() if not (t.isdigit() and len(t) == 4))
    return strip(period) == strip(prev_period)


def trend_md(ind: Indicator, cur, prev, prev_period: str | None, period: str | None = None) -> str:
    """'▼ -12,5% vs. 2025 PE IX' coloured green/red by whether the change is good."""
    if not ind.trend or cur is None or prev is None or not _same_period(period, prev_period):
        return ''
    cur, prev = float(cur), float(prev)
    if ind.trend == 'pp':
        delta = cur - prev
        txt = f'{delta:+.1f}'.replace('.', ',') + ' p.p.'
    elif ind.trend == 'abs':
        # Counts (cases): a percentage on small numbers reads as alarming noise
        delta = cur - prev
        txt = f'{delta:+,.0f} {ind.unit}'.replace(',', '.')
    else:
        if prev == 0:
            return ''
        delta = (cur - prev) / abs(prev) * 100
        txt = f'{delta:+.1f}%'.replace('.', ',')
    if abs(delta) < 0.05:
        color, arrow = _FLAT, '►'
    else:
        better = (delta < 0) if ind.lower_is_better else (delta > 0)
        color = _FLAT if ind.lower_is_better is None else (_GOOD if better else _BAD)
        arrow = '▼' if delta < 0 else '▲'
    ref = f' vs. {html.escape(prev_period)}' if prev_period else ' vs. año anterior'
    return f'<span class="fct-trend" style="color:{color}">{arrow} <b>{txt}</b>{ref}</span>'


_SHARE_OF = {'pob_hombres': 'pob_total', 'pob_mujeres': 'pob_total', 'pob_etnica': 'pob_total',
             'ips_publica': 'ips_total', 'ips_privada': 'ips_total', 'ips_mixta': 'ips_total'}


def share_note(ind: Indicator, row) -> str:
    """'48,7% del total' for the indicators the mockup shows as a share."""
    base = _SHARE_OF.get(ind.key)
    v, tot = _v(row, ind.col), _v(row, base) if base else None
    if v is None or not tot:
        return ''
    return f'{float(v) / float(tot) * 100:.1f}% del total'.replace('.', ',')


def money(v) -> str:
    """Pesos in compact Spanish form: '$ 3,48 billones', '$ 6,2 mil millones',
    '$ 840 mil millones', '$ 56,7 millones'."""
    if v is None:
        return 'N/D'
    v = float(v)
    if abs(v) >= 1e12:
        s, unit = f'{v / 1e12:,.2f}', 'billones'
    elif abs(v) >= 1e9:
        s, unit = f'{v / 1e9:,.{1 if abs(v) < 1e11 else 0}f}', 'mil millones'
    else:
        s, unit = f'{v / 1e6:,.1f}', 'millones'
    return f"$ {s.replace(',', '§').replace('.', ',').replace('§', '.')} {unit}"


def spark_svg(values: list, color: str, width: int = 220, height: int = 30) -> str:
    """Inline SVG sparkline (inside a card, unlike a Plotly chart)."""
    vals = [float(v) for v in values if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return ''
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = width / (len(vals) - 1)
    pts = ' '.join(f'{i * step:.1f},{height - 3 - (v - lo) / span * (height - 6):.1f}'
                   for i, v in enumerate(vals))
    return (f'<svg class="fct-spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" width="100%">'
            f'<polyline points="0,{height} {pts} {width},{height}" fill="{color}1A" stroke="none"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def _card(color: str, icon: str, label: str, value_html: str, unit: str, trend: str,
          period: str, note: str, extra: str = '', pending: bool = False) -> str:
    foot = ((f'<div class="fct-period">Datos: {html.escape(period)}</div>' if period else '')
            + (f'<div>{html.escape(note)}</div>' if note else ''))
    tip = ' · '.join(x for x in (label, period and f'Datos: {period}', note) if x)
    return (f'<div class="fct-card{" pending" if pending else ""}" style="--c:{color}" '
            f'title="{html.escape(tip)}">'
            f'<div class="fct-card-h"><span class="fct-ico">{html.escape(icon)}</span>'
            f'<span class="fct-label">{html.escape(label)}</span></div>'
            f'<div class="fct-card-v">{value_html}</div>'
            f'<div class="fct-unit">{html.escape(unit)}</div>{trend}{extra}'
            f'<div class="fct-card-f">{foot}</div></div>')


def kpi_card(module: str, ind: Indicator, row, prev=None, note: str = '',
             spark: list | None = None) -> None:
    """One indicator card (fixed size). row/prev: metric rows for the selection and
    for the same period one year earlier. spark: optional series drawn in the card."""
    if ind.col is None:
        return pending_card(module, ind)
    color = MODULES[module][1]
    col, period_col = ind.col, ind.period_col
    cur = _v(row, col)
    if cur is None and ind.fallback and _v(row, ind.fallback[0]) is not None:
        col, period_col, fb_note = ind.fallback
        cur = _v(row, col)
        note = ' · '.join(x for x in (fb_note, note) if x)
    prev_period = _v(prev, period_col) if period_col else None
    period = _v(row, period_col) if period_col else None
    value = f'<span class="fct-value{"" if cur is not None else " nd"}">{fmt(ind, cur)}</span>'
    st.markdown(_card(color, ind.icon, ind.label, value, ind.unit if ind.unit != '%' else '',
                      trend_md(ind, cur, _v(prev, col), prev_period, period),
                      str(period) if period else '', note,
                      spark_svg(spark, color) if spark else ''), unsafe_allow_html=True)


def pending_card(module: str, ind: Indicator) -> None:
    st.markdown(_card('#90A4AE', ind.icon, ind.label,
                      '<span class="fct-value nd small">Fuente pendiente</span>', '', '', '',
                      ind.pending, pending=True), unsafe_allow_html=True)


def card_grid(module: str, indicators: list[Indicator], row, prev=None, per_row: int = 4,
              notes: dict[str, str] | None = None) -> None:
    for i in range(0, len(indicators), per_row):
        cols = st.columns(per_row)
        for col, ind in zip(cols, indicators[i:i + per_row]):
            with col:
                kpi_card(module, ind, row, prev, (notes or {}).get(ind.key, ''))


@contextmanager
def panel(module: str, title: str, icon: str = '', subtitle: str = ''):
    """White titled box in the module colour, for charts and tables."""
    color = MODULES[module][1]
    key = re.sub(r'[^a-z0-9]+', '-', title.lower().encode('ascii', 'ignore').decode()).strip('-')
    with st.container(key=f'panel-{module}-{key}'):
        st.markdown(f'<div class="fct-panel-h" style="color:{color}">'
                    + (f'<span class="fct-ico">{html.escape(icon)}</span>' if icon else '')
                    + f'{html.escape(title)}</div>'
                    + (f'<div class="fct-panel-sub">{html.escape(subtitle)}</div>' if subtitle else ''),
                    unsafe_allow_html=True)
        yield


def chart(fig, key: str | None = None) -> None:
    """Plotly figure with the dashboard's settings: no toolbar, and no scroll-zoom
    (the mouse wheel scrolls the page, not the map)."""
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={'displayModeBar': False, 'scrollZoom': False})


def footer(text: str, sources: list[str]) -> None:
    src = ' · '.join(SRC[s] for s in sources if s in SRC)
    st.markdown(f'<div class="fct-footer">ⓘ {html.escape(text)}<br><b>Fuente:</b> {html.escape(src)}</div>',
                unsafe_allow_html=True)
