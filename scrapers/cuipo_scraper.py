# -*- coding: utf-8 -*-
"""
Scraper CUIPO — ejecución presupuestal de los entes territoriales en salud.

CUIPO (Categoría Única de Información del Presupuesto Ordinario, CGR / CHIP)
reemplazó al FUT. La Contraloría la publica en datos.gov.co (Socrata, sin
autenticación), trimestral y acumulada en el año (periodo AAAAMM01, MM = 03,
06, 09, 12):

  9axr-9gnb  ingresos — ejecución   (total_recaudo)
  4f7r-epif  gastos — ejecución     (compromisos, obligaciones, pagos)
  d9mu-h6ar  gastos — programación  (apropiación inicial / definitiva)

Cada dataset tiene ~12 M filas: los GROUP BY en el servidor exceden el tiempo
de espera. Se descargan las filas de salud de un periodo (≈25 k filas, segundos)
y se agregan aquí, por entidad:

  cuipo_salud_AAAAMM.parquet   una fila por entidad territorial y periodo

Entidades: gobernaciones (A438), municipios (A439), Bogotá (A440) y San Andrés
(A441). El código CGN termina en el código DIVIPOLA: municipios 21xx + DIVIPOLA5
(210105001 → 05001), departamentos 11xx + DD000 (112525000 → 25000).
Excepción: municipios creados después del catálogo CGN original llevan códigos
923xxxxxx sin DIVIPOLA; se mapean en _CGN_DIVIPOLA (verificado por nombre
contra DANE, 2026-10-13).

Fondo Local de Salud (FLS):
  ingresos   filas con detalle sectorial 'FLS-…' o fuente de salud (SGP salud,
             SGSSS, sus recursos del balance / rendimientos). ~20 % de los
             municipios no marca el detalle FLS; la fuente lo cubre.
  gastos     salud = código programático MGA 19xx (Salud y Protección Social) o
             detalle sectorial 19.xx. El detalle sectorial no se diligenció en
             2023 (Medellín 2023-T4: 0 filas), el MGA sí; en 2026 coinciden
             (Medellín: 1.073 vs 1.080 mil millones). Vigencia actual (incl.
             vigencias futuras de la actual); se excluyen reservas y cuentas
             por pagar de años anteriores.
SGP salud (fuentes 1.2.4.2.0x, solo recursos de la vigencia):
  .02 salud pública   .04 subsidio a la oferta

Fondos de salud con presupuesto propio (_FONDOS): donde la salud se ejecuta en
un establecimiento público aparte y la entidad territorial no lo consolida, el
fondo reemplaza a la entidad en las columnas indicadas (2026-T2, en miles de
millones):
  Bogotá      FFDS: recaudo FLS 1.650 vs 593 del distrito, cuyos compromisos
              incluyen las transferencias al fondo. El SGP salud pública lo
              ejecuta el distrito → solo se reemplazan las columnas FLS.
  N. Santander IDS: compromisos 80 vs 43 de la gobernación → todo.
Caldas (DTSC) y Nariño (IDSN) ya vienen consolidados en la gobernación (mismas
cifras). Arauca (UAESA) no reporta a CUIPO.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

API = 'https://www.datos.gov.co'
INGRESOS, GASTOS, PROGRAMACION = '9axr-9gnb', '4f7r-epif', 'd9mu-h6ar'
AMBITOS = ('A438', 'A439', 'A440', 'A441')
START = 202301          # first periodo (AAAAMM) to load
PAGE = 50_000
_PROBE_ENTITY = '210105001'   # Medellín: cheap way to list the published periods

# fondo CGN code → (territory CGN code, columns it replaces)
_FONDOS = {
    '225511001': ('210111001', 'fls'),        # Fondo Financiero Distrital de Salud → Bogotá
    '124754000': ('115454000', 'fls|sgp'),    # Instituto Departamental de Salud → Norte de Santander
}
_AMB = ("(ambito_codigo in(" + ','.join(f"'{a}'" for a in AMBITOS) + ") "
        "OR codigo_entidad in(" + ','.join(f"'{c}'" for c in _FONDOS) + "))")
_VIG = "cod_vigencia_del_gasto in('1','4')"   # vigencia actual (+ vigencias futuras de la actual)
_SGP = {'sp': '1.2.4.2.02', 'of': '1.2.4.2.04'}
_CGN_DIVIPOLA = {
    '923270346': 19300,   # Guachené (Cauca)
    '923271475': 23682,   # San José de Uré (Córdoba)
    '923271489': 13490,   # Norosí (Bolívar)
    '923271490': 23815,   # Tuchín (Córdoba)
    '923272927': 94343,   # Barrancominas (Guainía)
    '923273478': 27493,   # Nuevo Belén de Bajirá (Chocó)
}
_SALUD = "(starts_with(cod_programatico_mga, '19') OR starts_with(cod_sectorial, '19'))"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers['User-Agent'] = 'informe-regional/1.0 (Supersalud)'
    return s


def _get(s: requests.Session, url: str, params: dict | None = None, retries: int = 4):
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=(15, 300))
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ScrapeError(f'cuipo: HTTP {r.status_code} en {url}: {r.text[:200]}')
            log.warning(f'cuipo: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'cuipo: {type(e).__name__}, reintento {attempt + 1}/{retries}')
        time.sleep(10 * (attempt + 1))
    raise ScrapeError(f'cuipo: sin respuesta de {url}')


def _updated_at(s: requests.Session, ds: str) -> datetime:
    meta = _get(s, f'{API}/api/views/{ds}.json')
    return datetime.fromtimestamp(meta['rowsUpdatedAt'], tz=timezone.utc)


def _periods(s: requests.Session) -> list[str]:
    """Periods published in all three datasets (AAAAMM01), from START on."""
    sets = []
    for ds in (INGRESOS, GASTOS, PROGRAMACION):
        rows = _get(s, f'{API}/resource/{ds}.json', {
            '$select': 'periodo', '$where': f"codigo_entidad='{_PROBE_ENTITY}'",
            '$group': 'periodo', '$limit': 1000})
        sets.append({r['periodo'] for r in rows if r.get('periodo')})
    common = set.intersection(*sets)
    return sorted(p for p in common if int(p[:6]) >= START)


def _rows(s: requests.Session, ds: str, select: str, where: str) -> pl.DataFrame:
    out, offset = [], 0
    while True:
        page = _get(s, f'{API}/resource/{ds}.json', {
            '$select': select, '$where': where, '$order': ':id',
            '$limit': PAGE, '$offset': offset})
        out += page
        if len(page) < PAGE:
            break
        offset += PAGE
    cols = [c.strip() for c in select.split(',')]
    return pl.DataFrame(out, schema={c: pl.String for c in cols}) if out else \
        pl.DataFrame(schema={c: pl.String for c in cols})


def _num(c: str) -> pl.Expr:
    return pl.col(c).cast(pl.Float64, strict=False).fill_null(0)


def _period(s: requests.Session, periodo: str) -> pl.DataFrame:
    p = f"periodo='{periodo}' AND {_AMB}"
    ing = _rows(s, INGRESOS, 'codigo_entidad, nombre_entidad, ambito_codigo, '
                'cod_fuentes_financiacion, total_recaudo',
                f"{p} AND (starts_with(nom_detalle_sectorial, 'FLS') "
                f"OR upper(nom_fuentes_financiacion) like '%SALUD%')")
    gas = _rows(s, GASTOS, 'codigo_entidad, nombre_entidad, ambito_codigo, '
                'cod_fuentes_financiacion, compromisos, obligaciones, pagos',
                f"{p} AND {_SALUD} AND {_VIG}")
    pro = _rows(s, PROGRAMACION, 'codigo_entidad, nombre_entidad, ambito_codigo, '
                'apropiacion_inicial, apropiacion_definitiva',
                f"{p} AND {_SALUD} AND {_VIG}")
    if gas.is_empty() or ing.is_empty():
        raise ScrapeError(f'cuipo: periodo {periodo} sin filas de salud '
                          f'(ingresos {len(ing)}, gastos {len(gas)})')

    fu = pl.col('cod_fuentes_financiacion')
    i = ing.group_by('codigo_entidad').agg(
        _num('total_recaudo').sum().alias('fls_recaudo'),
        *[_num('total_recaudo').filter(fu == f).sum().alias(f'sgp_{k}_recaudo') for k, f in _SGP.items()])
    g = gas.group_by('codigo_entidad').agg(
        _num('compromisos').sum().alias('fls_compromisos'),
        _num('obligaciones').sum().alias('fls_obligaciones'),
        _num('pagos').sum().alias('fls_pagos'),
        *[_num(c).filter(fu == f).sum().alias(f'sgp_{k}_{c}')
          for k, f in _SGP.items() for c in ('compromisos', 'pagos')])
    a = pro.group_by('codigo_entidad').agg(
        _num('apropiacion_inicial').sum().alias('fls_apropiacion_inicial'),
        _num('apropiacion_definitiva').sum().alias('fls_apropiacion_definitiva'))
    names = pl.concat([d.select('codigo_entidad', 'nombre_entidad', 'ambito_codigo')
                       for d in (ing, gas, pro)]).unique('codigo_entidad', keep='first')

    df = (names.join(i, on='codigo_entidad', how='left')
               .join(g, on='codigo_entidad', how='left')
               .join(a, on='codigo_entidad', how='left'))
    dept = pl.col('ambito_codigo').is_in(['A438', 'A441'])
    df = _apply_fondos(df)
    divipola = (pl.col('codigo_entidad').replace_strict(_CGN_DIVIPOLA, default=None, return_dtype=pl.Int32)
                .fill_null(pl.col('codigo_entidad').str.slice(-5).cast(pl.Int32)))
    return df.with_columns(
        pl.lit(int(periodo[:4])).alias('anio'),
        pl.lit(int(periodo[4:6])).alias('mes'),
        pl.when(dept).then(pl.lit('departamento')).otherwise(pl.lit('municipio')).alias('nivel'),
        (divipola // 1000).cast(pl.Int32).alias('codigo_dep'),
        pl.when(dept).then(None).otherwise(divipola).alias('codigo_mun'),
    )


def _apply_fondos(df: pl.DataFrame) -> pl.DataFrame:
    """Copy each health fund's columns onto its territory's row, then drop the fund."""
    for fondo, (territorio, groups) in _FONDOS.items():
        src = df.filter(pl.col('codigo_entidad') == fondo)
        if src.is_empty() or df.filter(pl.col('codigo_entidad') == territorio).is_empty():
            continue
        cols = [c for c in df.columns if c.startswith(tuple(f'{g}_' for g in groups.split('|')))]
        vals = src.row(0, named=True)
        df = df.with_columns([pl.when(pl.col('codigo_entidad') == territorio).then(pl.lit(vals[c]))
                              .otherwise(pl.col(c)).alias(c) for c in cols])
    return df.filter(~pl.col('codigo_entidad').is_in(list(_FONDOS)))


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    s = _session()
    updated = max(_updated_at(s, ds) for ds in (INGRESOS, GASTOS, PROGRAMACION))
    periods = _periods(s)
    if not periods:
        raise ScrapeError('cuipo: no se encontraron periodos publicados')
    log.info(f'CUIPO: {len(periods)} periodos ({periods[0]}–{periods[-1]}), '
             f'actualizado {updated:%Y-%m-%d}')

    done = 0
    for periodo in periods:
        out = parquet_dir / f'cuipo_salud_{periodo[:6]}.parquet'
        # CGR revises earlier quarters too: refetch whenever the datasets changed
        # after the file was written.
        if out.exists() and datetime.fromtimestamp(out.stat().st_mtime, tz=timezone.utc) > updated:
            continue
        df = _period(s, periodo)
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        done += 1
        print(f'  -> {out.name} ({len(df):,} entidades, '
              f'compromisos salud ${df["fls_compromisos"].sum() / 1e12:,.2f} billones)')

    print(f'cuipo_scraper OK — {done} periodo(s) descargado(s), {len(periods) - done} sin cambios')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
