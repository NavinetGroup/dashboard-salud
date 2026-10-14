# -*- coding: utf-8 -*-
"""Visual building blocks for the FCT design: module header, KPI cards with a
trend vs. the same period of the previous year, "fuente pendiente" cards and
the source footer. Icons are Streamlit's bundled Material Symbols (work offline).
"""

import html

import pandas as pd
import streamlit as st

from registry import MODULES, SRC, Indicator

_GOOD, _BAD, _FLAT = '#2E7D32', '#C62828', '#F9A825'


def inject_css() -> None:
    accents = '\n'.join(
        f'[class*="st-key-card-{m}-"] {{ border-top: 4px solid {c} !important; }}'
        for m, (_, c, _) in MODULES.items())
    st.markdown(f"""
<style>
[class*="st-key-card-"] {{
    background: #FFFFFF; border-radius: 14px !important;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06); padding: 4px 6px; min-height: 178px;
}}
{accents}
[class*="st-key-card-"].pending, [class*="st-key-pend-"] {{
    background: #F5F7F8; border-top: 4px solid #CFD8DC !important; min-height: 178px;
    border-radius: 14px !important;
}}
.fct-label  {{ font-size: 12.5px; font-weight: 700; color: #37474F; text-transform: uppercase;
               letter-spacing: .3px; line-height: 1.25; min-height: 32px; }}
.fct-value  {{ font-size: 30px; font-weight: 800; line-height: 1.1; margin-top: 2px; }}
.fct-unit   {{ font-size: 12px; color: #78909C; margin-top: 2px; }}
.fct-trend  {{ font-size: 12.5px; margin-top: 8px; padding: 4px 8px; border-radius: 8px;
               display: inline-block; background: #F5F7F8; }}
.fct-period {{ font-size: 11px; color: #90A4AE; margin-top: 6px; }}
.fct-pend   {{ font-size: 12px; color: #78909C; margin-top: 6px; }}
.fct-header {{ border-radius: 16px; padding: 18px 24px; color: white; margin-bottom: 14px; }}
.fct-header h1 {{ color: white; font-size: 30px; margin: 0; padding: 0; font-weight: 800; }}
.fct-header p  {{ color: rgba(255,255,255,.88); margin: 4px 0 0 0; font-size: 15px; }}
.fct-crumb  {{ font-size: 14px; color: rgba(255,255,255,.9); margin-top: 6px; }}
.fct-footer {{ background: #EEF5F5; border-radius: 12px; padding: 10px 16px; font-size: 12.5px;
               color: #455A64; margin-top: 16px; }}
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


def kpi_card(module: str, ind: Indicator, row, prev=None, note: str = '') -> None:
    """One indicator card. row/prev: metric rows for the selection and for the same
    period one year earlier."""
    if ind.col is None:
        return pending_card(module, ind)
    color = MODULES[module][1]
    col, period_col = ind.col, ind.period_col
    cur = _v(row, col)
    if cur is None and ind.fallback and _v(row, ind.fallback[0]) is not None:
        col, period_col, fb_note = ind.fallback
        cur = _v(row, col)
        note = ' · '.join(x for x in (fb_note, note) if x)
    with st.container(border=True, key=f'card-{module}-{ind.key}'):
        st.markdown(f':material/{ind.icon}: <span class="fct-label">{html.escape(ind.label)}</span>',
                    unsafe_allow_html=True)
        prev_period = _v(prev, period_col) if period_col else None
        period = _v(row, period_col) if period_col else None
        st.markdown(
            f'<div class="fct-value" style="color:{color if cur is not None else "#B0BEC5"}">'
            f'{fmt(ind, cur)}</div>'
            f'<div class="fct-unit">{html.escape(ind.unit if ind.unit != "%" else "")}</div>'
            f'{trend_md(ind, cur, _v(prev, col), prev_period, period)}'
            + (f'<div class="fct-period">Datos: {html.escape(str(period))}</div>' if period else '')
            + (f'<div class="fct-pend">{html.escape(note)}</div>' if note else ''),
            unsafe_allow_html=True)


def pending_card(module: str, ind: Indicator) -> None:
    with st.container(border=True, key=f'pend-{module}-{ind.key}'):
        st.markdown(f':material/{ind.icon}: <span class="fct-label">{html.escape(ind.label)}</span>',
                    unsafe_allow_html=True)
        st.markdown('<div class="fct-value" style="color:#B0BEC5;font-size:20px">Fuente pendiente</div>'
                    f'<div class="fct-pend">{html.escape(ind.pending)}</div>', unsafe_allow_html=True)


def card_grid(module: str, indicators: list[Indicator], row, prev=None, per_row: int = 4,
              notes: dict[str, str] | None = None) -> None:
    for i in range(0, len(indicators), per_row):
        cols = st.columns(per_row)
        for col, ind in zip(cols, indicators[i:i + per_row]):
            with col:
                kpi_card(module, ind, row, prev, (notes or {}).get(ind.key, ''))


def footer(text: str, sources: list[str]) -> None:
    src = ' · '.join(SRC[s] for s in sources if s in SRC)
    st.markdown(f'<div class="fct-footer">ⓘ {html.escape(text)}<br><b>Fuente:</b> {html.escape(src)}</div>',
                unsafe_allow_html=True)
