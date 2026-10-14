# -*- coding: utf-8 -*-
"""
Scraper cofinanciación del régimen subsidiado (Financiamiento, indicador 8).

Meta — MSPS "Monto estimado de recursos del régimen subsidiado" (matriz de
continuidad), uno por vigencia con ajustes durante el año (SGP, Coljuegos); se
usa la versión más reciente publicada. Esfuerzo propio que cada entidad
territorial se compromete a girar:
  municipal      Coljuegos + juegos de suerte y azar / rentas cedidas (solo
                 Bogotá) + Coljuegos de vigencias anteriores
  departamental  Coljuegos + rentas cedidas (licores, cigarrillo, cerveza, …),
                 municipalizado: valor por municipio

Ejecución — ADRES "Resultado LMA" (Liquidación Mensual de Afiliados), un
archivo por mes con el detalle municipio × EPS × fuente. Es la misma fuente con
la que MSPS arma la "Matriz ejecutada" al cierre del año. Esfuerzo propio
girado en el mes, por nivel:
  Coljuegos + total girado por ADRES (rentas cedidas que la ADRES recauda) +
  esfuerzo propio que la entidad territorial gira directamente a la EPS

Salidas (data/parquet):
  cofin_meta_AAAA.parquet         codigo_mun → meta_mun, meta_dep (pesos/año)
  cofin_lma_AAAA_MM.parquet       codigo_mun → girado_mun, girado_dep (pesos/mes)
"""

import io
import logging
import re
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

START_YEAR = 2023
ADRES = 'https://www.adres.gov.co'
MSPS = 'https://www.minsalud.gov.co'
MSPS_PAGE = f'{MSPS}/Proteccion-Social/financiamiento/Paginas/matriz-continuidad.aspx'
_MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre']


def _session() -> requests.Session:
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (informe-regional; Supersalud)'
    return s


def _get(s: requests.Session, url: str, params: dict | None = None, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=(15, 300))
            if r.status_code == 200:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ScrapeError(f'cofinanciacion: HTTP {r.status_code} en {url}')
            log.warning(f'cofinanciacion: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'cofinanciacion: {type(e).__name__}, reintento {attempt + 1}/{retries}')
        time.sleep(10 * (attempt + 1))
    raise ScrapeError(f'cofinanciacion: sin respuesta de {url}')


def _norm(s) -> str:
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().upper()


def _xlsx(content: bytes) -> bytes:
    """The workbook itself, unzipping when ADRES / MSPS publish it as a .zip."""
    if content[:2] != b'PK':
        raise ScrapeError('cofinanciacion: el archivo no es xlsx ni zip')
    zf = zipfile.ZipFile(io.BytesIO(content))
    if '[Content_Types].xml' in zf.namelist():   # already an xlsx
        return content
    books = [n for n in zf.namelist() if n.lower().endswith(('.xlsx', '.xlsm', '.xls'))]
    if not books:
        raise ScrapeError(f'cofinanciacion: zip sin Excel ({zf.namelist()[:5]})')
    return zf.read(books[0])


def _headers(raw: pl.DataFrame, anchor: str, depth: int) -> tuple[int, list[str]]:
    """Locate the header row (the one whose cells include `anchor`) and build one
    name per column from it and the next `depth - 1` rows, forward-filling the
    group titles of merged cells: 'GRUPO || SUBCOLUMNA'."""
    for i in range(min(30, raw.height)):
        if any(_norm(v) == anchor for v in raw.row(i)):
            break
    else:
        raise ScrapeError(f'cofinanciacion: encabezado "{anchor}" no encontrado')
    rows = [raw.row(i + k) for k in range(depth)]
    names, group = [], ''
    for j in range(raw.width):
        top = _norm(rows[0][j])
        if top:
            group = top
        # Some files repeat a vertically merged cell in every header row ('DANE || DANE')
        parts = [group] + [_norm(r[j]) for r in rows[1:] if _norm(r[j]) and _norm(r[j]) != group]
        names.append(' || '.join(parts))
    return i, names


def _cols(names: list[str], *patterns: str) -> list[int]:
    out = [j for j, n in enumerate(names) if all(re.search(p, n) for p in patterns)]
    return out


# ── LMA (ADRES) ──────────────────────────────────────────────────────────────

def _lma_index(s: requests.Session) -> dict[tuple[int, int], dict]:
    """(year, month) → newest media document of the monthly LMA summary.
    ADRES names files inconsistently (case, spaces, duplicates); 'Consolidado'
    files are skipped (the monthly ones carry the same rows)."""
    docs, page = [], 1
    while True:
        d = _get(s, f'{ADRES}/api/media', {'where[filename][like]': 'liquidacion-mensual-de-afiliados',
                                           'limit': 100, 'page': page, 'depth': 0}).json()
        docs += d.get('docs', [])
        if not d.get('hasNextPage'):
            break
        page += 1
    idx: dict[tuple[int, int], dict] = {}
    pat = re.compile(r'afiliados[-\s]+([a-z]+)[-\s]+(\d{4})\.(xlsx|zip)$', re.I)
    for doc in docs:
        m = pat.search(doc.get('filename') or '')
        if not m or m.group(1).lower() not in _MESES:
            continue
        key = (int(m.group(2)), _MESES.index(m.group(1).lower()) + 1)
        if key not in idx or (doc.get('updatedAt') or '') > (idx[key].get('updatedAt') or ''):
            idx[key] = doc
    return idx


def _parse_lma(content: bytes) -> pl.DataFrame:
    raw = pl.read_excel(io.BytesIO(_xlsx(content)), sheet_name='DETALLE', engine='calamine',
                        has_header=False, infer_schema_length=0)
    hdr, names = _headers(raw, 'DANE', 2)
    pick = {
        'girado_mun': (_cols(names, r'^COLJUEGOS', r'\|\| MUNICIPAL$')
                       + _cols(names, r'^TOTAL MUNICIPAL GIRADO POR ADRES')
                       + _cols(names, r'^RECURSOS ESFUERZO PROPIO A GIRAR', r'MUNICIPAL$')),
        'girado_dep': (_cols(names, r'^COLJUEGOS', r'\|\| DEPARTAMENTAL$')
                       + _cols(names, r'^TOTAL DEPARTAMENTAL GIRADO POR ADRES')
                       + _cols(names, r'^RECURSOS ESFUERZO PROPIO A GIRAR', r'DEPARTAMENTAL$')),
    }
    for k, js in pick.items():
        if len(js) != 3:
            raise ScrapeError(f'cofinanciacion: LMA, columnas de {k} no reconocidas ({[names[j] for j in js]})')
    dane = names.index('DANE')
    body = raw.slice(hdr + 2)
    num = lambda j: pl.col(raw.columns[j]).cast(pl.Float64, strict=False).fill_null(0)
    return (body.filter(pl.col(raw.columns[dane]).str.contains(r'^\d{4,5}$'))
                .select(pl.col(raw.columns[dane]).cast(pl.Int32).alias('codigo_mun'),
                        *[pl.sum_horizontal([num(j) for j in js]).alias(k) for k, js in pick.items()])
                .group_by('codigo_mun').agg(pl.all().sum()))


# ── Matriz de continuidad (MSPS) ─────────────────────────────────────────────

def _meta_links(s: requests.Session) -> dict[int, str]:
    """year → URL of the newest 'Monto estimado de recursos' version. The page
    lists versions newest first within each year."""
    html = _get(s, MSPS_PAGE).text
    out: dict[int, str] = {}
    for href, text in re.findall(r'href="([^"]+\.zip)"[^>]*>(.*?)</a>', html, re.S):
        text = _norm(re.sub('<[^>]+>', '', text))
        m = re.search(r'MONTO ESTIMADO.*?(20\d\d)', text)
        if m and int(m.group(1)) not in out:
            out[int(m.group(1))] = href if href.startswith('http') else MSPS + href
    return out


def _parse_meta(content: bytes) -> pl.DataFrame:
    book = _xlsx(content)
    sheets = pl.read_excel(io.BytesIO(book), sheet_id=0, engine='calamine', has_header=False,
                           infer_schema_length=0)
    raw = next((df for name, df in sheets.items() if _norm(name).startswith('MONTO ESTIMADO')),
               next(iter(sheets.values())))
    hdr, names = _headers(raw, 'CODIGO DANE', 1)
    # Group titles ('… ESFUERZO PROPIO MUNICIPIO', '… DEPARTAMENTO') sit one row
    # above the column headers; each group runs until the next one starts.
    groups = [_norm(v) for v in raw.row(hdr - 1)]
    start_mun = next((j for j, g in enumerate(groups) if 'ESFUERZO PROPIO MUNICIPIO' in g), None)
    start_dep = next((j for j, g in enumerate(groups) if 'ESFUERZO PROPIO DEPARTAMENTO' in g), None)
    ep = [j for j, n in enumerate(names) if re.search(r'^(RECURSOS TRANSFERIDOS POR COLJUEGOS|JUEGOS DE SUERTE Y AZAR)', n)]
    if start_mun is None or start_dep is None or not ep:
        raise ScrapeError(f'cofinanciacion: matriz sin columnas de esfuerzo propio ({groups})')
    mun = [j for j in ep if start_mun <= j < start_dep]
    dep = [j for j in ep if j >= start_dep]
    code = raw.columns[names.index('CODIGO DANE')]
    num = lambda j: pl.col(raw.columns[j]).cast(pl.Float64, strict=False).fill_null(0)
    return (raw.slice(hdr + 1)   # one header row: data starts right below it
               .filter(pl.col(code).str.contains(r'^\d{4,5}$'))
               .select(pl.col(code).cast(pl.Int32).alias('codigo_mun'),
                       pl.sum_horizontal([num(j) for j in mun]).alias('meta_mun'),
                       pl.sum_horizontal([num(j) for j in dep]).alias('meta_dep')))


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)
    s = _session()
    today = date.today()

    # Meta: closed years once; the current one whenever MSPS publishes a new version
    for year, url in sorted(_meta_links(s).items()):
        if not START_YEAR <= year <= today.year:
            continue
        out = parquet_dir / f'cofin_meta_{year}.parquet'
        if out.exists() and year < today.year:
            continue
        df = _parse_meta(_get(s, url).content).with_columns(
            pl.lit(year).alias('anio'), pl.lit(url.rsplit('/', 1)[-1]).alias('version'))
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        print(f'  -> {out.name} ({df.height:,} municipios, meta esfuerzo propio '
              f'${(df["meta_mun"].sum() + df["meta_dep"].sum()) / 1e9:,.0f} mil millones)')

    # LMA: one file per month, refetched only when ADRES replaces it
    done = 0
    for (year, month), doc in sorted(_lma_index(s).items()):
        if year < START_YEAR or (year, month) > (today.year, today.month):
            continue
        out = parquet_dir / f'cofin_lma_{year}_{month:02d}.parquet'
        stamp = doc.get('updatedAt') or ''
        if out.exists() and pl.read_parquet(out, columns=['stamp'])['stamp'][0] >= stamp:
            continue
        df = _parse_lma(_get(s, ADRES + doc['url']).content).with_columns(
            pl.lit(year).alias('anio'), pl.lit(month).alias('mes'), pl.lit(stamp).alias('stamp'))
        if df.height < 1000:
            raise ScrapeError(f'cofinanciacion: LMA {year}-{month:02d} con solo {df.height} municipios')
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        done += 1
        print(f'  -> {out.name} ({df.height:,} municipios, esfuerzo propio girado '
              f'${(df["girado_mun"].sum() + df["girado_dep"].sum()) / 1e9:,.1f} mil millones)')
    print(f'cofinanciacion_scraper OK — {done} mes(es) LMA descargado(s)')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
