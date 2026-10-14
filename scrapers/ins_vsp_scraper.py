# -*- coding: utf-8 -*-
"""
Scraper INS — indicadores de evaluación del desempeño de la vigilancia en salud
pública (VSP) de las entidades territoriales (Salud pública FCT 10 y 11).

Fuente: Portal SIVIGILA, biblioteca SharePoint "Documentos compartidos" (REST,
sin login). Un Excel por trimestre: primero "PRELIMINAR", luego "FINAL"; los
nombres no son uniformes ("… I 2026 FINAL", "… ET 2025 I FINAL", "… II TRIM
2024 ET", …). Se ignoran los de EAPB (evaluación de las EPS).

Cada archivo: filas = subindicadores (grupos 1–8), columnas = entidad
territorial (32 departamentos con código DD000 y los distritos con su código
municipal: 08001, 11001, 13001, 47001, 76001, 76109). Valores 0–1 o "NA" (no
aplica en el trimestre).

Salida: data/parquet/ins_vsp_AAAA_T.parquet (formato largo)
  anio, trimestre, estado, codigo_entidad, entidad, grupo, subindicador,
  descripcion, valor (NULL = no aplica)
"""

import io
import logging
import re
import time
import urllib.parse
from pathlib import Path

import polars as pl
import requests

try:
    from scrapers.errors import ScrapeError
except ImportError:  # run directly as `python scrapers/<name>.py`
    from errors import ScrapeError

log = logging.getLogger(__name__)

PORTAL = 'https://portalsivigila.ins.gov.co'
LIBRARY = 'Documentos'          # list title of "Documentos compartidos"
_ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (informe-regional; Supersalud)',
                      'Accept': 'application/json;odata=nometadata'})
    return s


def _get(s: requests.Session, url: str, params: dict | None = None, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=(15, 300))
            if r.status_code == 200:
                return r
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ScrapeError(f'ins_vsp: HTTP {r.status_code} en {url}')
            log.warning(f'ins_vsp: HTTP {r.status_code}, reintento {attempt + 1}/{retries}')
        except requests.RequestException as e:
            log.warning(f'ins_vsp: {type(e).__name__}, reintento {attempt + 1}/{retries}')
        time.sleep(10 * (attempt + 1))
    raise ScrapeError(f'ins_vsp: sin respuesta de {url}')


def _quarter_files(s: requests.Session) -> dict[tuple[int, int], dict]:
    """(year, quarter) → the file to use: FINAL over PRELIMINAR, newest first."""
    items = _get(s, f"{PORTAL}/_api/web/lists/GetByTitle('{LIBRARY}')/items",
                 {'$select': 'FileRef,Modified', '$top': 5000}).json().get('value', [])
    best: dict[tuple[int, int], dict] = {}
    for it in items:
        ref = it.get('FileRef') or ''
        name = ref.rsplit('/', 1)[-1]
        up = name.upper()
        if 'DESEMPE' not in up or 'EAPB' in up or not up.endswith('.XLSX'):
            continue
        tokens = re.split(r'[\s_.-]+', name[:-5])
        years = [int(t) for t in tokens if re.fullmatch(r'20\d\d', t)]
        quarters = [_ROMAN[t.upper()] for t in tokens if t.upper() in _ROMAN]
        if len(years) != 1 or len(quarters) != 1:
            log.warning(f'ins_vsp: nombre no reconocido, se omite: {name}')
            continue
        final = 'PRELIMINAR' not in up
        cand = {'ref': ref, 'name': name, 'final': final, 'modified': it.get('Modified') or ''}
        key = (years[0], quarters[0])
        cur = best.get(key)
        if cur is None or (final, cand['modified']) > (cur['final'], cur['modified']):
            best[key] = cand
    return best


def _parse(content: bytes) -> pl.DataFrame:
    """Two layouts: 2026 has a 'Grupo Indicador' column before 'Subindicador';
    2024–2025 start with 'Subindicador'. Columns are located by their header and
    the group is taken from the sub-indicator number ('2-18' → 2) in both."""
    sheets = pl.read_excel(io.BytesIO(content), sheet_id=0, engine='calamine', has_header=False,
                           infer_schema_length=0)
    raw = next(iter(sheets.values()))
    hdr = sub_col = None
    for i in range(min(15, raw.height)):
        for j in range(min(4, raw.width)):
            if str(raw.row(i)[j] or '').strip().upper() == 'SUBINDICADOR':
                hdr, sub_col = i, j
                break
        if hdr is not None:
            break
    if not hdr:
        raise ScrapeError('ins_vsp: no se encontró la columna "Subindicador"')
    codes, names = raw.row(hdr - 1), raw.row(hdr)
    ents = [(j, str(codes[j]).strip().zfill(5), str(names[j]).strip())
            for j in range(sub_col + 2, raw.width)
            if codes[j] and re.fullmatch(r'\d{4,5}', str(codes[j]).strip())]
    if len(ents) < 33:
        raise ScrapeError(f'ins_vsp: solo {len(ents)} entidades en el encabezado')
    rows = []
    for i in range(hdr + 1, raw.height):
        r = raw.row(i)
        sub = str(r[sub_col] or '').strip()
        m = re.match(r'(?i)subindicador\s+(\d+)-(\d+)', sub)
        if not m:
            continue
        desc = str(r[sub_col + 1] or '').strip()
        for j, code, ent in ents:
            v = r[j]
            try:
                val = float(str(v).replace(',', '.')) if v is not None and str(v).strip() else None
            except ValueError:   # 'NA', 'N/A', 'No aplica'
                val = None
            rows.append((code, ent, int(m.group(1)), f'{m.group(1)}-{m.group(2)}', desc, val))
    return pl.DataFrame(rows, schema=['codigo_entidad', 'entidad', 'grupo', 'subindicador',
                                      'descripcion', 'valor'], orient='row')


def run(base_dir: str = None) -> None:
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    parquet_dir.mkdir(parents=True, exist_ok=True)
    s = _session()
    files = _quarter_files(s)
    if not files:
        raise ScrapeError('ins_vsp: no se encontraron archivos de evaluación del desempeño')
    done = 0
    for (year, q), f in sorted(files.items()):
        out = parquet_dir / f'ins_vsp_{year}_{q}.parquet'
        stamp = f'{f["name"]}|{f["modified"]}'
        if out.exists() and pl.read_parquet(out, columns=['fuente'])['fuente'][0] == stamp:
            continue
        content = _get(s, PORTAL + urllib.parse.quote(f['ref'])).content
        df = _parse(content).with_columns(
            pl.lit(year).alias('anio'), pl.lit(q).alias('trimestre'),
            pl.lit('FINAL' if f['final'] else 'PRELIMINAR').alias('estado'), pl.lit(stamp).alias('fuente'))
        df.write_parquet(out, compression='zstd', use_pyarrow=True)
        done += 1
        print(f'  -> {out.name} ({df["codigo_entidad"].n_unique()} entidades, '
              f'{df["subindicador"].n_unique()} subindicadores, {"FINAL" if f["final"] else "PRELIMINAR"})')
    print(f'ins_vsp_scraper OK — {done} trimestre(s) actualizado(s) de {len(files)}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
