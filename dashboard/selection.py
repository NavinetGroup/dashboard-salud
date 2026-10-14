# -*- coding: utf-8 -*-
"""Sidebar selection shared by every page: period, department, municipality.

Widgets live in the entry script (app.py), so the choice persists while the user
moves between pages. Each page receives a Selection with the metric rows it
needs: the entity, its department, the nation, and the same period one year
earlier for each (trend arrows).
"""

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from data import (get_available_months, get_available_years, get_dept_metrics,
                  get_mun_metrics, get_nat_metrics, get_prev_metrics)


@dataclass
class Selection:
    year: int | None
    month: str | None              # None = latest available in the year
    period_label: str
    dept_name: str
    dept_code: int
    dept_row: pd.Series
    mun_name: str | None
    mun_code: int | None
    mun_row: pd.Series | None
    df_dept: pd.DataFrame
    df_mun: pd.DataFrame
    nat_row: pd.Series
    prev_dept: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    prev_mun: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    prev_nat: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))

    @property
    def use_mun(self) -> bool:
        return self.mun_row is not None

    @property
    def entity_row(self) -> pd.Series:
        return self.mun_row if self.use_mun else self.dept_row

    @property
    def prev_entity(self) -> pd.Series:
        return self.prev_mun if self.use_mun else self.prev_dept

    @property
    def entity_name(self) -> str:
        return self.mun_name if self.use_mun else self.dept_name

    def row_for(self, dept_only: bool) -> tuple[pd.Series, pd.Series, str]:
        """(row, prev, label) for an indicator: the municipality when it has its own
        value, otherwise its department (INS entity tables; districts excepted)."""
        if self.use_mun and not dept_only:
            return self.mun_row, self.prev_mun, self.mun_name
        return self.dept_row, self.prev_dept, self.dept_name


def sidebar() -> Selection:
    with st.sidebar.container(key='filtros'):
        st.markdown('<div class="fct-filtros-title">FILTROS</div>', unsafe_allow_html=True)
        return _filters()


def _filters() -> Selection:
    years = get_available_years()
    year = st.selectbox('Año de referencia', years, index=0, key='sel_year') if years else None
    month = None
    if year is not None:
        opts = ['Último disponible'] + get_available_months(year)
        m = st.selectbox('Mes de referencia', opts, index=0, key='sel_month')
        month = None if m == 'Último disponible' else m

    df_dept = get_dept_metrics(year=year, month=month)
    depts = df_dept['departamento'].dropna().tolist()
    if not depts:
        st.error('La base de datos no tiene departamentos. Ejecute el pipeline y recargue.')
        st.stop()
    dept_name = st.selectbox('Departamento', depts, key='sel_dept')
    dept_row = df_dept[df_dept['departamento'] == dept_name].iloc[0]
    dept_code = int(dept_row['geo_dep_codigo'])

    df_mun = get_mun_metrics(dept_code, year=year, month=month)
    mun_name = mun_row = mun_code = None
    muns = df_mun['municipio'].dropna().tolist()
    choice = st.selectbox('Municipio', ['— Todo el departamento —'] + muns, key='sel_mun')
    if choice in muns:
        mun_name = choice
        mun_row = df_mun[df_mun['municipio'] == choice].iloc[0]
        mun_code = int(mun_row['geo_mun_codigo'])

    label = (f'{month.title()} {year}' if month else f'{year} (último disponible)') if year else 'Último disponible'
    sel = Selection(
        year=year, month=month, period_label=label,
        dept_name=dept_name, dept_code=dept_code, dept_row=dept_row,
        mun_name=mun_name, mun_code=mun_code, mun_row=mun_row,
        df_dept=df_dept, df_mun=df_mun,
        nat_row=get_nat_metrics(year=year, month=month),
        prev_dept=get_prev_metrics('departamento', year, month, dept_code),
        prev_mun=get_prev_metrics('municipio', year, month, mun_code) if mun_code else pd.Series(dtype=object),
        prev_nat=get_prev_metrics('nacional', year, month),
    )
    st.caption(f'Periodo: **{label}** · cada indicador indica el periodo de sus datos.')
    return sel
