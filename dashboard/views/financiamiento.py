# -*- coding: utf-8 -*-
"""Financiamiento — ejecución presupuestal y flujos de recursos (FCT).

No source is integrated yet: indicators 1–8 will come from CUIPO (CGR),
SICODIS (DNP), ADRES and MinSalud files; 9–11 must be supplied by the client.
See docs/FUENTES_INVESTIGACION_2026-10-13.md.
"""

import streamlit as st

from registry import FINANCIAMIENTO
from ui import card_grid, footer, module_header

sel = st.session_state['sel']

module_header('financiamiento', 'Ejecución presupuestal y flujos de recursos en salud', sel)

st.info('Este módulo está en construcción: las fuentes ya están identificadas (CUIPO, SICODIS, '
        'ADRES, matriz de cofinanciación MSPS) y se integrarán en la siguiente fase. Los indicadores '
        '9 a 11 requieren información interna de Supersalud / MSPS.', icon=':material/construction:')

card_grid('financiamiento', FINANCIAMIENTO[:3], None, per_row=3)
card_grid('financiamiento', FINANCIAMIENTO[3:7], None, per_row=4)
card_grid('financiamiento', FINANCIAMIENTO[7:9], None, per_row=2)
card_grid('financiamiento', FINANCIAMIENTO[9:], None, per_row=2)

footer('Los indicadores permitirán monitorear la gestión financiera de los recursos del sistema de '
       'salud, su ejecución y el cumplimiento de obligaciones.', ['cuipo'])
