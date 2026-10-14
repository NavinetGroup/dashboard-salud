# -*- coding: utf-8 -*-
"""Informe Regional de Salud — entry point.

Multipage app in the layout of the client's "Ficha de Caracterización Territorial"
(docs/reference/DASHBOARD_FCT.docx): a menu, the one-page Ficha, five modules and
the original detailed report. The sidebar selection (period, department,
municipality) lives here so it persists across pages; each page reads it from
st.session_state['sel'].
"""

from pathlib import Path

import streamlit as st

from data import data_version
from selection import sidebar
from ui import inject_css

st.set_page_config(page_title='Informe Regional de Salud', layout='wide',
                   initial_sidebar_state='expanded', page_icon=':material/health_and_safety:')

_LOGO = Path(__file__).parent / 'Logo-Supersalud-2024.svg'
if _LOGO.exists():
    st.logo(str(_LOGO), size='large')

inject_css()
st.session_state['sel'] = sidebar()
_version = data_version()
if _version:   # viewer database: say which published version is on screen
    st.sidebar.caption(f'Datos: versión {_version}')

pages = {
    '': [
        st.Page('views/inicio.py', title='Inicio', icon=':material/home:', default=True),
        st.Page('views/ficha.py', title='Ficha territorial', icon=':material/assignment:'),
    ],
    'Módulos': [
        st.Page('views/demograficos.py', title='Demográficos', icon=':material/groups:'),
        st.Page('views/salud_publica.py', title='Salud pública', icon=':material/ecg_heart:'),
        st.Page('views/aseguramiento.py', title='Aseguramiento', icon=':material/verified_user:'),
        st.Page('views/prestacion.py', title='Prestación de servicios', icon=':material/local_hospital:'),
        st.Page('views/financiamiento.py', title='Financiamiento', icon=':material/payments:'),
    ],
}
st.navigation(pages).run()
