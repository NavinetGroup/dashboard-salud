# -*- coding: utf-8 -*-
"""Financiamiento — ejecución presupuestal y flujos de recursos (FCT).

Indicators 1–7: CUIPO (CGR, quarterly, year-to-date) and SICODIS (DNP, SGP
allocations); 8: MSPS co-financing matrix + ADRES monthly LMA. Computed in
pipeline/metricas.py; the formulas are a proposal pending Supersalud
validation (docs/FINANCIAMIENTO_FORMULAS.md). 9–11 must be supplied by the client.
"""

import streamlit as st

from registry import FINANCIAMIENTO
from ui import footer, kpi_card, module_header, money, pending_card, _v

sel = st.session_state['sel']
row, prev = sel.entity_row, sel.prev_entity

module_header('financiamiento', 'Ejecución presupuestal y flujos de recursos en salud', sel)

if sel.use_mun:
    scope = f'Presupuesto de salud del municipio de {sel.mun_name}'
elif sel.dept_code == 11:
    scope = 'Presupuesto de salud de Bogotá D.C. (Fondo Financiero Distrital de Salud)'
elif sel.dept_code:
    scope = f'Presupuesto de salud de la gobernación de {sel.dept_name} (sin sus municipios)'
else:
    scope = 'Total nacional: todas las gobernaciones, distritos y municipios'
st.caption(f'{scope}. Ejecución acumulada en el año al corte del trimestre (CUIPO). '
           'Fórmulas propuestas, pendientes de validación con Supersalud.')


_AMOUNTS = {   # (numerator, denominator) columns and their labels
    'fin1': (('fls_compromisos', 'Compromisos'), ('fls_recaudo', 'ingresos FLS')),
    'fin2': (('fls_compromisos', 'Compromisos'), ('fls_apropiacion_definitiva', 'apropiación')),
    'fin3': (('fls_pagos', 'Pagos'), ('fls_recaudo', 'ingresos FLS')),
    'fin8': (('cofin_girado', 'Girado'), ('cofin_meta_anual', 'meta anual')),
}


def _note(ind) -> str:
    if ind.key in _AMOUNTS and _v(row, ind.col) is not None:
        (n, nl), (d, dl) = _AMOUNTS[ind.key]
        txt = f'{nl} {money(_v(row, n))} · {dl} {money(_v(row, d))}'
        return txt + (' · 100 % = al día con la meta prorrateada' if ind.key == 'fin8' else '')
    # No SGP subsidio a la oferta allocation (≈⅔ of municipalities) → NULL, not 0 %
    if ind.key in ('fin6', 'fin7') and _v(row, ind.col) is None and _v(row, 'fin_sgp_sp_comp') is not None:
        return 'Sin asignación SGP de subsidio a la oferta'
    return ''


def _grid(inds, per_row):
    for col, ind in zip(st.columns(per_row), inds):
        with col:
            if ind.col is None:
                pending_card('financiamiento', ind)
            else:
                kpi_card('financiamiento', ind, row, prev, _note(ind))


_grid(FINANCIAMIENTO[:3], 3)
_grid(FINANCIAMIENTO[3:7], 4)
_grid(FINANCIAMIENTO[7:9], 2)
_grid(FINANCIAMIENTO[9:], 2)

footer('Ingresos FLS: recaudo con destinación al Fondo Local de Salud (detalle sectorial FLS o fuentes de '
       'salud). Compromisos y pagos: gasto del sector salud (MGA 19) de la vigencia. Indicadores SGP: '
       'compromisos, pagos o giros recibidos de cada participación ÷ asignación SICODIS del año. '
       'Cofinanciación: esfuerzo propio girado al régimen subsidiado (LMA) ÷ meta anual de la matriz MSPS.',
       ['cuipo', 'sicodis', 'cofin'])
