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
CARD_H = 262          # px: every KPI card, so cards in a row and across rows line up


_SIDEBAR_BG = 'linear-gradient(180deg, #0B5D5E 0%, #084A4B 100%)'
_NAV_EXTRA: dict[str, str] = {}   # pages outside MODULES: their chip colour


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
/* ── KPI card (FCT mockup): numbered centred title, big icon in a tinted circle
   beside the value, optional visual (scale, bar, donut), trend box, data date ── */
.fct-card {{
    height: {CARD_H}px; display: flex; flex-direction: column; overflow: hidden; text-align: center;
    background: #FFFFFF; border-radius: 16px; border: 1px solid #E3ECEE;
    box-shadow: 0 2px 10px rgba(0,0,0,.06); padding: 12px 12px 8px 12px; margin-bottom: 14px; }}
.fct-card.pending {{ background: #F7F9FA; box-shadow: none; }}
.fct-wrap {{ container-type: inline-size; }}
/* narrow cards (6 to a row): icon above the value, centred */
@container (max-width: 205px) {{
  .fct-card-m {{ flex-direction: column; gap: 2px; }}
  .fct-card-m .vv {{ text-align: center; }}
  .fct-bigico {{ width: 40px; height: 40px; min-width: 40px; line-height: 40px; font-size: 24px; }}
}}
.fct-value.long {{ font-size: 25px; }}
.fct-card-t {{ font-size: 11.5px; font-weight: 800; color: var(--c); text-transform: uppercase;
    letter-spacing: .3px; line-height: 1.3; min-height: 45px; display: -webkit-box;
    -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
.fct-card-m {{ display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 4px; }}
.fct-bigico {{ font-family: 'Material Symbols Rounded'; font-size: 34px; line-height: 54px; width: 54px;
    height: 54px; min-width: 54px; border-radius: 50%; background: var(--cl); color: var(--c);
    -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; font-weight: normal;
    font-style: normal; text-transform: none; letter-spacing: normal; }}
.fct-card-m .vv {{ text-align: left; min-width: 0; }}
.fct-value  {{ font-size: 30px; font-weight: 800; line-height: 1.05; color: var(--c); white-space: nowrap; }}
.fct-value.nd {{ color: #B0BEC5; }}
.fct-value.small {{ font-size: 16px; white-space: normal; line-height: 1.2; }}
.fct-unit   {{ font-size: 11.5px; color: #607D8B; margin-top: 2px; line-height: 1.25; display: -webkit-box;
    -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.fct-vis {{ margin-top: 8px; }}
.fct-card-b {{ margin-top: auto; }}
.fct-tbox {{ border-radius: 10px; padding: 4px 8px; font-size: 11.5px; line-height: 1.3; }}
.fct-tbox .k {{ font-size: 10.5px; opacity: .8; }}
.fct-tbox b {{ font-size: 15px; }}
.fct-card-f {{ font-size: 10.5px; color: #90A4AE; line-height: 1.3; margin-top: 4px; }}
.fct-card-f div {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.fct-card-f .fct-period {{ -webkit-line-clamp: 1; }}
.fct-card-f .fct-note {{ color: #607D8B; }}
.fct-ico {{ font-family: 'Material Symbols Rounded'; font-size: 18px; line-height: 17px;
    color: var(--c, #546E7A); font-weight: normal; font-style: normal; letter-spacing: normal;
    text-transform: none; white-space: nowrap; -webkit-font-feature-settings: 'liga';
    font-feature-settings: 'liga'; -webkit-font-smoothing: antialiased; }}
/* scale bar (IRCA risk, capacities, co-financing): coloured segments + marker */
.fct-scale {{ position: relative; margin: 14px 4px 0 4px; }}
.fct-scale .seg {{ display: flex; gap: 3px; height: 9px; }}
.fct-scale .seg span {{ flex: 1; border-radius: 5px; }}
.fct-scale .mk {{ position: absolute; top: -13px; transform: translateX(-50%); font-size: 13px;
    line-height: 13px; color: #263238; }}
.fct-scale .tk {{ display: flex; justify-content: space-between; font-size: 9.5px; color: #90A4AE;
    margin-top: 2px; }}
.fct-scale .lv {{ font-size: 11.5px; font-weight: 700; margin-top: 2px; }}
/* progress bar (budget execution) */
.fct-prog {{ height: 9px; background: #ECEFF1; border-radius: 5px; overflow: hidden; margin: 8px 6px 0 6px; }}
.fct-prog span {{ display: block; height: 100%; border-radius: 5px; background: var(--c); }}
/* mini donut + legend (VSP compliance) */
.fct-md {{ display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 6px; }}
.fct-md .lg {{ text-align: left; font-size: 11px; color: #455A64; line-height: 1.45; }}
.fct-md .lg i {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; }}
/* ── panel: white titled box for charts and tables ─────────────────────────── */
[class*="st-key-panel-"] {{ background: #FFFFFF; border-radius: 16px; border-top: 4px solid #CFD8DC;
    box-shadow: 0 2px 10px rgba(0,0,0,.07); padding: 12px 16px 8px 16px; margin-bottom: 14px; }}
{panels}
.fct-panel-h {{ font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: .4px;
    display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }}
.fct-panel-h .fct-ico {{ color: inherit; }}
.fct-panel-sub {{ font-size: 12px; color: #78909C; margin: -2px 0 4px 0; }}
.fct-header {{ border-radius: 16px; padding: 18px 24px; color: white; margin-bottom: 14px;
    display: flex; align-items: center; gap: 20px; position: relative; overflow: hidden; }}
.fct-header .hico {{ font-family: 'Material Symbols Rounded'; font-size: 56px; line-height: 56px;
    color: white; -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga';
    padding-right: 20px; border-right: 1px solid rgba(255,255,255,.35); }}
.fct-header .deco {{ font-family: 'Material Symbols Rounded'; position: absolute; right: 24px; top: 50%;
    transform: translateY(-50%); font-size: 110px; line-height: 110px; color: rgba(255,255,255,.16);
    -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; }}
.fct-header h1 {{ color: white; font-size: 30px; margin: 0; padding: 0; font-weight: 800; }}
.fct-header p  {{ color: rgba(255,255,255,.88); margin: 4px 0 0 0; font-size: 15px; }}
.fct-crumb  {{ font-size: 14px; color: rgba(255,255,255,.9); margin-top: 6px; }}
.fct-cap {{ display: flex; align-items: center; gap: 18px; padding: 4px 0 6px 0; }}
.fct-cap .big {{ font-family: 'Material Symbols Rounded'; font-size: 64px; line-height: 110px; width: 110px;
    min-width: 110px; height: 110px; border-radius: 50%; text-align: center;
    -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; }}
.fct-cap .ls {{ flex: 1; }}
.fct-cap .it {{ display: flex; align-items: center; gap: 10px; padding: 5px 0; border-bottom: 1px solid #EEF2F3; }}
.fct-cap .it:last-child {{ border-bottom: none; }}
.fct-cap .ic {{ font-family: 'Material Symbols Rounded'; font-size: 18px; line-height: 30px; width: 30px;
    height: 30px; border-radius: 50%; text-align: center; -webkit-font-feature-settings: 'liga';
    font-feature-settings: 'liga'; }}
.fct-cap .lb {{ flex: 1; font-size: 13.5px; color: #37474F; }}
.fct-cap .vl {{ font-size: 20px; font-weight: 800; }}
.fct-conv {{ background: #F5F9F9; border-radius: 14px; padding: 10px 16px; font-size: 12.5px;
    color: #455A64; display: flex; flex-wrap: wrap; gap: 6px 24px; align-items: center; margin-top: 4px; }}
.fct-conv .h {{ font-weight: 800; color: #0B5D5E; letter-spacing: .5px; width: 100%; font-size: 12px; }}
.fct-conv .d {{ display: inline-block; border-radius: 6px; padding: 1px 6px; font-weight: 800; margin-right: 6px; }}
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
        f'<span class="hico">{icon}</span><div>'
        f'<h1>{html.escape(title.upper())}</h1><p>{html.escape(subtitle)}</p>'
        f'<div class="fct-crumb">{html.escape(crumb)} · {html.escape(sel.period_label)}</div></div>'
        f'<span class="deco">{icon}</span></div>',
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


def _trend(ind: Indicator, cur, prev, prev_period: str | None, period: str | None = None):
    """(arrow, text, colour, reference) for the change vs. the same period a year
    earlier, or None when there is nothing comparable."""
    if not ind.trend or cur is None or prev is None or not _same_period(period, prev_period):
        return None
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
            return None
        delta = (cur - prev) / abs(prev) * 100
        txt = f'{delta:+.1f}%'.replace('.', ',')
    if abs(delta) < 0.05:
        color, arrow = _FLAT, '►'
    else:
        better = (delta < 0) if ind.lower_is_better else (delta > 0)
        color = _FLAT if ind.lower_is_better is None else (_GOOD if better else _BAD)
        arrow = '▼' if delta < 0 else '▲'
    ref = f'vs. {html.escape(prev_period)}' if prev_period else 'vs. año anterior'
    return arrow, txt, color, ref


_TBOX_BG = {_GOOD: '#E8F5E9', _BAD: '#FDECEA', _FLAT: '#FFF8E1'}


def trend_box(ind: Indicator, cur, prev, prev_period: str | None, period: str | None = None) -> str:
    """The mockup's 'Tendencia' box: tinted green / red / amber by the direction."""
    tr = _trend(ind, cur, prev, prev_period, period)
    if not tr:
        return ''
    arrow, txt, color, ref = tr
    return (f'<div class="fct-tbox" style="background:{_TBOX_BG.get(color, "#F5F7F8")};color:{color}">'
            f'<span class="k">Tendencia</span> <b>{arrow} {txt}</b><br><span class="k">{ref}</span></div>')


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
          period: str, note: str, extra: str = '', pending: bool = False, num: int | None = None) -> str:
    foot = ((f'<div class="fct-period">Datos: {html.escape(period)}</div>' if period else '')
            + (f'<div class="fct-note">{html.escape(note)}</div>' if note else ''))
    title = f'{num}. {label}' if num else label
    tip = ' · '.join(x for x in (title, period and f'Datos: {period}', note) if x)
    return (f'<div class="fct-wrap"><div class="fct-card{" pending" if pending else ""}" style="--c:{color};--cl:{color}1F" '
            f'title="{html.escape(tip)}">'
            f'<div class="fct-card-t">{html.escape(title)}</div>'
            f'<div class="fct-card-m"><span class="fct-bigico">{html.escape(icon)}</span>'
            f'<div class="vv">{value_html}<div class="fct-unit">{html.escape(unit)}</div></div></div>'
            f'{f"<div class=fct-vis>{extra}</div>" if extra else ""}'
            f'<div class="fct-card-b">{trend}<div class="fct-card-f">{foot}</div></div></div></div>')


def scale_html(value: float | None, bands: list[tuple[float, str]], lo: float = 0, hi: float = 100,
               ticks: list | None = None, level: str = '', level_color: str = '#455A64') -> str:
    """Segmented scale with a marker at `value` (IRCA risk, capacities, co-financing).
    bands: [(upper bound, colour)] covering lo..hi, drawn as equal segments."""
    if value is None:
        return ''
    v = max(lo, min(hi, float(value)))
    # position the marker within the segment it falls in (segments are equal width)
    edges = [lo] + [b for b, _ in bands]
    k = next((i for i in range(len(bands)) if v <= edges[i + 1]), len(bands) - 1)
    frac = (v - edges[k]) / ((edges[k + 1] - edges[k]) or 1)
    pos = (k + frac) / len(bands) * 100
    segs = ''.join(f'<span style="background:{c}"></span>' for _, c in bands)
    tk = ''.join(f'<span>{x}</span>' for x in (ticks or []))
    return (f'<div class="fct-scale"><div class="mk" style="left:{pos:.1f}%">▼</div>'
            f'<div class="seg">{segs}</div>' + (f'<div class="tk">{tk}</div>' if ticks else '')
            + (f'<div class="lv" style="color:{level_color}">{html.escape(level)}</div>' if level else '')
            + '</div>')


def progress_html(pct: float | None) -> str:
    if pct is None:
        return ''
    return f'<div class="fct-prog"><span style="width:{max(0.0, min(100.0, float(pct))):.1f}%"></span></div>'


def mini_donut_html(parts: list[tuple[float, str, str]], size: int = 64) -> str:
    """SVG donut + legend. parts: [(percent, colour, label)]."""
    r, c = 15.915, 0.0
    arcs = ''
    for pct, color, _ in parts:
        if pct > 0:
            arcs += (f'<circle r="{r}" cx="21" cy="21" fill="transparent" stroke="{color}" stroke-width="7" '
                     f'stroke-dasharray="{pct:.2f} {100 - pct:.2f}" stroke-dashoffset="{25 - c:.2f}"/>')
        c += pct
    lg = ''.join(f'<div><i style="background:{color}"></i>{html.escape(lbl)} '
                 f'<b>{pct:.0f} %</b></div>' for pct, color, lbl in parts)
    return (f'<div class="fct-md"><svg width="{size}" height="{size}" viewBox="0 0 42 42">{arcs}</svg>'
            f'<div class="lg">{lg}</div></div>')


def kpi_card(module: str, ind: Indicator, row, prev=None, note: str = '',
             spark: list | None = None, num: int | None = None, visual: str = '') -> None:
    """One indicator card (fixed size). row/prev: metric rows for the selection and
    for the same period one year earlier. spark: optional series drawn in the card."""
    if ind.col is None:
        return pending_card(module, ind, num)
    color = MODULES[module][1]
    col, period_col = ind.col, ind.period_col
    cur = _v(row, col)
    if cur is None and ind.fallback and _v(row, ind.fallback[0]) is not None:
        col, period_col, fb_note = ind.fallback
        cur = _v(row, col)
        note = ' · '.join(x for x in (fb_note, note) if x)
    prev_period = _v(prev, period_col) if period_col else None
    period = _v(row, period_col) if period_col else None
    txt = fmt(ind, cur)
    cls = ' nd' if cur is None else (' long' if len(txt) > 7 else '')
    value = f'<span class="fct-value{cls}">{txt}</span>'
    st.markdown(_card(color, ind.icon, ind.label, value, ind.unit if ind.unit != '%' else '',
                      trend_box(ind, cur, _v(prev, col), prev_period, period),
                      str(period) if period else '', note,
                      visual or (spark_svg(spark, color) if spark else ''), num=num), unsafe_allow_html=True)


def pending_card(module: str, ind: Indicator, num: int | None = None) -> None:
    st.markdown(_card('#90A4AE', ind.icon, ind.label,
                      '<span class="fct-value nd small">Fuente pendiente</span>', '', '', '',
                      ind.pending, pending=True, num=num), unsafe_allow_html=True)


def card_grid(module: str, indicators: list[Indicator], row, prev=None, per_row: int = 4,
              notes: dict[str, str] | None = None, start: int | None = None) -> None:
    """Cards per_row to a row; start numbers them as in the mockup (1., 2., …)."""
    for i in range(0, len(indicators), per_row):
        cols = st.columns(per_row)
        for j, (col, ind) in enumerate(zip(cols, indicators[i:i + per_row])):
            with col:
                kpi_card(module, ind, row, prev, (notes or {}).get(ind.key, ''),
                         num=start + i + j if start else None)


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
    st.plotly_chart(fig, width='stretch', key=key,
                    config={'displayModeBar': False, 'scrollZoom': False})


def footer(text: str, sources: list[str]) -> None:
    src = ' · '.join(SRC[s] for s in sources if s in SRC)
    st.markdown(f'<div class="fct-footer">ⓘ {html.escape(text)}<br><b>Fuente:</b> {html.escape(src)}</div>',
                unsafe_allow_html=True)
