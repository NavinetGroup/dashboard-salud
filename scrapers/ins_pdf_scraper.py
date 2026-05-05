# -*- coding: utf-8 -*-
"""
Scraper genérico para informes epidemiológicos periódicos del INS (PDF).

URL patrón:
  https://www.ins.gov.co/buscador-eventos/Informesdeevento/{EVENTO}_PE_{PERIODO}_{AÑO}.pdf

Periodos epidemiológicos colombianos: 13 por año (~4 semanas c/u).

Comportamiento:
- Itera sobre TODOS los periodos desde START_YEAR PE I hasta el PE actual publicado.
- Cada periodo escribe su propio parquet estampado (ins_{key}_PE_{roman}_{year}[_tabla{i}].parquet).
- Parquets ya existentes se omiten (caché incremental).
- Future-ready: el formato de URL es genérico; nuevos periodos se descargan automáticamente.

Salidas: data/parquet/ins_{nombre_evento}_PE_{periodo}_{anio}[_tabla{i}].parquet
"""

import io
import logging
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote

import duckdb
import polars as pl
import requests

log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

BASE_INS = 'https://www.ins.gov.co/buscador-eventos/Informesdeevento'
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII']

# First year to scrape historical data from
START_YEAR = 2025

# Normalized Colombian department names (DANE PPED canonical).
# Used to reject tables that contain EPS/institution names instead of geographic entities.
_COLOMBIA_DEPARTMENTS: frozenset[str] = frozenset({
    'AMAZONAS', 'ANTIOQUIA', 'ARAUCA', 'ATLANTICO', 'BOGOTA D C',
    'BOLIVAR', 'BOYACA', 'CALDAS', 'CAQUETA', 'CASANARE', 'CAUCA', 'CESAR',
    'CHOCO', 'CORDOBA', 'CUNDINAMARCA', 'GUAINIA', 'GUAVIARE', 'HUILA',
    'LA GUAJIRA', 'MAGDALENA', 'META', 'NARINO', 'NORTE DE SANTANDER',
    'PUTUMAYO', 'QUINDIO', 'RISARALDA',
    'SAN ANDRES PROVIDENCIA Y SANTA CATALINA',
    'SANTANDER', 'SUCRE', 'TOLIMA', 'VALLE DEL CAUCA', 'VAUPES', 'VICHADA',
    # Special districts that report separately
    'BARRANQUILLA', 'CARTAGENA', 'CALI', 'SANTA MARTA', 'BUENAVENTURA',
})

# Approximate start week of each epidemiological period (1-indexed ISO weeks)
PE_START_WEEKS = [1, 5, 9, 13, 18, 22, 26, 31, 35, 40, 44, 48, 52]

# ---------------------------------------------------------------------------
# Event configurations
# page: 0-indexed PDF page number
# tables: list of 0-indexed table indices on that page (None = all)
# ---------------------------------------------------------------------------

EVENTS = [
    {
        'key': 'mortalidad_materna',
        'url_name': 'MORTALIDAD MATERNA',
        'page': 2,
        'tables': [0, 1, 2],
        'column_schema': [
            # Tabla 0 — Anexo N°1, departamentos (5 cols)
            ['entidad_territorial', 'casos_mm_previo', 'casos_mm_actual',
             'razon_mm_previo', 'razon_mm_actual'],
            # Tabla 1 — Anexo N°2, municipios 20 000-100 000 hab (6 cols)
            ['departamento', 'municipio', 'casos_mm_previo', 'casos_mm_actual',
             'razon_mm_previo', 'razon_mm_actual'],
            # Tabla 2 — Anexo N°3, municipios <20 000 hab (6 cols)
            ['departamento', 'municipio', 'casos_mm_previo', 'casos_mm_actual',
             'razon_mm_previo', 'razon_mm_actual'],
        ],
        # Filter out garbage tables (e.g. PE V 2025 page 2 has no valid data)
        'geo_validate_col': 'entidad_territorial',
        # Page 0 (infographic) table 3 = municipality-level deaths overview (all sizes combined)
        'extra_tables': [
            {
                'page': 0,
                'tables': [3],
                'column_schema': [
                    ['departamento', 'municipio', 'casos_mm_previo', 'casos_mm_actual',
                     'razon_mm_previo', 'razon_mm_actual'],
                ],
                'geo_validate_col': 'departamento',
            },
        ],
    },
    {
        'key': 'sifilis_congenita',
        'url_name': 'SÍFILIS CONGÉNITA',
        # Page 3 in PDF viewer (0-indexed: 2) = "Entidad territorial" table (~47 rows)
        # which covers all departments + 6 special districts including Bogotá D.C.
        'page': 2,
        'tables': [0],
        # Column layout confirmed from PDF: entity name, MF cases, MF%, NV SC cases, NV%, total SC.
        # 'casos_sc_nv' = nacidos vivos with SC (≈ national-total-matching count).
        # 'casos_sc_total' = NV + MF = total SC cases per entity (used as main case metric).
        'column_schema': [[
            'entidad_territorial', 'casos_sc_mf', 'pct_mf',
            'casos_sc_nv', 'pct_nv', 'casos_sc_total',
        ]],
        'geo_validate_col': 'entidad_territorial',
        'min_entity_rows': 30,  # entidad territorial table has ~47 rows; reject tiny fragments
        'fallback_pages': [1, 3, 4],
    },
    {
        'key': 'desnutricion_aguda',
        'url_name': 'DESNUTRICION AGUDA',
        'page': 1,
        'tables': [0, 1, 2],
        'column_schema': [
            ['departamento', 'municipio', 'casos', 'prevalencia_por_100'],
            ['departamento', 'municipio', 'casos', 'prevalencia_por_100'],
            ['departamento', 'municipio', 'casos', 'prevalencia_por_100'],
        ],
        'table_labels': ['menos_20000', 'entre_20000_100000', 'mas_100000'],
        # Some periods (e.g. 2026 PE_II+) have the EPS breakdown table at page 1 index 0;
        # reject tables where <30% of 'departamento' values are valid Colombian departments.
        'geo_validate_col': 'departamento',
        'fallback_pages': [2, 0, 3],
    },
    {
        'key': 'mortalidad_menores5',
        'url_name': 'MORTALIDAD EN MENORES DE 5 AÑOS',
        'page': 1,
        'tables': [0],
        'strategy': 'word_grid',
        # Entity column sits at x≈55-120 (outside pdfplumber borders).
        # Later PDFs have a concordance table (2-word rows) on the same page before the
        # rate table — min_data_cols=3 excludes those rows from entity_rows.
        # skip_header_text='Entidad' excludes the "Entidad territorial IRA DNT" header
        # row from col_starts computation (it has the same word count as data rows).
        'word_grid_options': {
            'entity_x_max': 120.0,
            'word_x_max': 320.0,   # EDA column sits at x≈295-308 across periods
            'n_cols_override': 4,
            'min_data_cols': 3,
            'section_header_text': 'Entidad',
            'min_entity_len': 4,   # excludes chart labels ('e','d') and 'DNT'/'IRA'/'EDA'
        },
        'column_names': ['entidad_territorial', 'tasa_dnt', 'tasa_ira', 'tasa_eda'],
    },
    {
        'key': 'dengue',
        'url_name': 'DENGUE',
        'page': 3,
        'tables': [0],
        'strategy': 'word_grid',  # entity col (x≈1) sits outside ruling-line borders
        'column_names': [
            'entidad_territorial', 'dengue_total', 'dengue_grave_total',
            'bajo_investigacion', 'incidencia_x100k',
            'sin_alarma_n', 'con_alarma_n', 'grave_n',
            'sin_alarma_confirmacion_pct', 'con_alarma_confirmacion_pct',
            'grave_confirmacion_pct',
            'con_alarma_hospitalizacion_pct', 'grave_hospitalizacion_pct',
            'muertes_confirmadas', 'letalidad_dengue_pct', 'letalidad_dengue_grave_pct',
        ],
        # Trim any header-fragment rows that appear above the first real data row
        'first_entity': 'Amazonas',
    },
    {
        'key': 'intento_suicidio',
        'url_name': 'INTENTO DE SUICIDIO',
        # The "entity territorial" section in these PDFs is a bar chart rendered
        # character-by-character — NOT extractable as a table.  The municipality tables
        # (ranked by incidence rate) ARE plain text and use word_grid:
        #   Page 1 (0-indexed): municipalities with >100 000 inhabitants (top 10)
        #   Page 2 (0-indexed): municipalities with <20 000 inhabitants (top ~20)
        # The 20 000–100 000 table on page 2 (top section) is also character-by-character
        # and cannot be extracted.
        # Column x-positions: Departamento≈250, Municipio≈338, Tasa≈465.
        # section_header_text='Departamento' anchors y_min just below the column header,
        # excluding the chart content that appears above the table on the same page.
        'page': 1,
        'strategy': 'word_grid',
        'word_grid_options': {
            'entity_x_max': 270.0,   # dept names at x≈243-263; mun names at x≈338+
            'word_x_max': 510.0,     # tasa values at x≈465-495
            'min_data_cols': 3,
            'section_header_text': 'Departamento',
            'min_entity_len': 4,
            'strict_page': True,
        },
        'column_names': ['departamento', 'municipio', 'tasa'],
        'geo_validate_col': 'departamento',
        'min_entity_rows': 5,
        'extra_tables': [
            {
                # Page 2 contains the <20 000 inhabitants municipality table.
                # Same column layout as page 1 table.
                'page': 2,
                'strategy': 'word_grid',
                'word_grid_options': {
                    'entity_x_max': 270.0,
                    'word_x_max': 510.0,
                    'min_data_cols': 3,
                    'section_header_text': 'Departamento',
                    'min_entity_len': 4,
                    'strict_page': True,
                },
                'column_names': ['departamento', 'municipio', 'tasa'],
            },
        ],
    },
    {
        'key': 'violencia_genero',
        'url_name': 'VIOLENCIA DE GÉNERO',
        'page': 1,
        'tables': [0],
        'strategy': 'word_grid',
        # Territorial breakdown (department-level, all Colombia) is borderless.
        # Entity column at x0≈4-11. Right-side two-column entities appear at x0≈322-364
        # (excluded by entity_x_max=30 from col_starts computation, skipped by
        # min_filled check in reconstruction). word_x_max=340 keeps all left-table
        # data columns while excluding most right-side entity names.
        # strict_page=True prevents fallback to other pages where municipality tables
        # or mutilation-genital tables would be incorrectly extracted.
        # section_header_text='Entidad' anchors y_min below the table header; its
        # absence on a page causes that page to be skipped — early periods (PE_I
        # through PE_X 2025) have no territorial breakdown and correctly return [].
        'word_grid_options': {
            'entity_x_max': 30.0,
            'word_x_max': 340.0,
            'min_data_cols': 6,
            'section_header_text': 'Entidad',
            'min_entity_len': 4,
            'strict_page': True,
        },
        'column_names': [
            'entidad_territorial', 'violencia_fisica', 'violencia_psicologica',
            'negligencia_abandono', 'violencia_sexual', 'violencia_genero_intrafamiliar',
        ],
        # Skip PDF header continuation rows ('de ocurrencia', year labels) before
        # the first real data entity. COLOMBIA is the national total row.
        'first_entity': 'COLOMBIA',
    },
]

# Alternate URL name encodings to try when primary fails
URL_NAME_VARIANTS = {
    'mortalidad_menores5': [
        'MORTALIDAD EN MENORES 5 AÑOS',
        'MORTALIDAD EN MENORES DE 5 AÑOS',
        'MORTALIDAD EN MENORES 5 A%C3%91OS',
        'MORTALIDAD EN MENORES DE 5 A%C3%91OS',
    ],
    'sifilis_congenita': [
        'S%C3%8DFILIS%20CONG%C3%89NITA',
        'SIFILIS CONGENITA',
    ],
    'violencia_genero': [
        'VIOLENCIA DE G%C3%89NERO',
        'VIOLENCIA DE GENERO',
    ],
    'dengue': [
        'DENGUE ',  # some early files have a trailing space before .pdf
    ],
}


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def _current_pe(ref_date: date | None = None) -> tuple[int, int]:
    """Return (pe_1based, year) for the most recently completed published PE."""
    ref = ref_date or date.today()
    year = ref.year
    week = ref.isocalendar()[1]

    pe = 1
    for i, start in enumerate(PE_START_WEEKS):
        if week >= start:
            pe = i + 1

    if pe == 1 and week < 3:
        return 13, year - 1
    if pe > 1:
        return pe - 1, year
    return 13, year - 1


def _all_periods(start_year: int = START_YEAR) -> list[tuple[int, int]]:
    """All (pe, year) from START_YEAR PE I up to (and including) current published PE."""
    now_pe, now_year = _current_pe()
    periods = []
    for year in range(start_year, now_year + 1):
        for pe in range(1, 14):
            if year == now_year and pe > now_pe:
                break
            periods.append((pe, year))
    return periods


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _build_url(event_url_name: str, periodo_roman: str, year: int) -> str:
    name_enc = quote(event_url_name, safe='%')  # preserve already-encoded sequences
    return f'{BASE_INS}/{name_enc}%20PE%20{periodo_roman}%20{year}.pdf'


def _download_pdf(url: str, retries: int = 3) -> bytes | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(10, 300), stream=True)
            if r.status_code == 200:
                ct = r.headers.get('content-type', '')
                if 'pdf' in ct or 'octet' in ct or not ct:
                    chunks = [c for c in r.iter_content(512 * 1024) if c]
                    data = b''.join(chunks)
                    if len(data) > 10_000:
                        return data
                    return None
            if r.status_code == 404:
                return None  # PDF not published — no point retrying
            log.debug(f'PDF: HTTP {r.status_code} — {url}')
            return None
        except Exception as e:
            if attempt < retries - 1:
                wait = 20 * (attempt + 1)
                log.debug(f'PDF: intento {attempt + 1} fallido, reintentando en {wait}s — {e}')
                time.sleep(wait)
            else:
                log.debug(f'PDF: {retries} intentos fallidos — {url} — {e}')
    return None


# ---------------------------------------------------------------------------
# Table extraction — 3-stage pipeline:
#   1. pdfplumber lines strategy  (vector PDFs with ruling lines)
#   2. pdfplumber text strategy   (vector PDFs with whitespace-separated columns)
#   3. Tesseract OCR              (image-based or complex-layout PDFs)
# ---------------------------------------------------------------------------

def _normalize_col(s: str) -> str:
    s = str(s).strip()
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', '_', s).lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9_]', '', s) or 'col'


def _raw_to_dataframes(raw_tables: list, table_indices: list[int]) -> list[pl.DataFrame]:
    """Convert a list of raw pdfplumber/OCR tables to Polars DataFrames."""
    results = []
    for tidx in table_indices:
        if tidx >= len(raw_tables):
            tidx = len(raw_tables) - 1
        raw = raw_tables[tidx]
        if not raw or len(raw) < 2:
            continue

        # Auto-detect header row
        headers_raw = raw[0]
        if all(h is None or str(h).strip() == '' for h in headers_raw):
            headers_raw = raw[1]
            data_rows = raw[2:]
        else:
            data_rows = raw[1:]

        headers = [_normalize_col(h) if h and str(h).strip() else f'col_{i}'
                   for i, h in enumerate(headers_raw)]

        # Deduplicate column names
        seen: dict[str, int] = {}
        deduped = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                deduped.append(f'{h}_{seen[h]}')
            else:
                seen[h] = 0
                deduped.append(h)

        rows = []
        for row in data_rows:
            if row is None:
                continue
            cells = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in row]
            padded = (cells + [''] * len(deduped))[:len(deduped)]
            rows.append(padded)

        if not rows:
            continue

        df = pl.DataFrame({col: [r[i] for r in rows] for i, col in enumerate(deduped)})
        df = df.filter(~pl.all_horizontal(pl.col(c) == '' for c in deduped[:1]))
        if len(df) > 0:
            results.append(df)

    return results


def _pages_to_try(page_idx: int, n_pages: int) -> list[int]:
    """Return candidate page indices to scan, starting with the specified page."""
    candidates = [page_idx]
    for delta in [-1, 1, -2, 2, -3, 3]:
        alt = page_idx + delta
        if 0 <= alt < n_pages and alt not in candidates:
            candidates.append(alt)
    return candidates


# --- Stage 1: pdfplumber lines ---

def _pdfplumber_tables(pdf_bytes: bytes, page_idx: int,
                       strategy: str = 'lines') -> tuple[list, int]:
    """
    Extract raw tables from a PDF using pdfplumber.

    strategy: 'lines' uses ruling-line detection (default);
              'text'  uses whitespace/character-spacing detection.
    Returns (raw_tables, actual_page_index_used).
    """
    import pdfplumber

    table_settings: dict = {}
    if strategy == 'text':
        table_settings = {
            'vertical_strategy': 'text',
            'horizontal_strategy': 'text',
            'min_words_vertical': 3,
            'min_words_horizontal': 1,
        }

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n_pages = len(pdf.pages)
        for p_idx in _pages_to_try(page_idx, n_pages):
            page = pdf.pages[p_idx]
            tables = page.extract_tables(table_settings) if table_settings else page.extract_tables()
            if tables:
                if p_idx != page_idx:
                    log.info(f'PDF [{strategy}]: tablas en pag {p_idx} (esperada {page_idx})')
                return tables, p_idx

    return [], page_idx


# --- Stage 2: pdfplumber word-grid ---

def _pdfplumber_word_grid(pdf_bytes: bytes, page_idx: int,
                          min_data_cols: int = 5,
                          entity_x_max: float = 30.0,
                          word_x_min: float = 0.0,
                          word_x_max: float | None = None,
                          n_cols_override: int | None = None,
                          first_entity: str | None = None,
                          section_header_text: str | None = None,
                          min_entity_len: int = 1,
                          col_names: list[str] | None = None,
                          strict_page: bool = False,
                          y_tolerance: int = 6) -> list:
    """
    Word bounding-box table reconstruction for complex multi-column layouts.

    Works when the first column sits outside any ruling-line border (e.g. dengue
    tables where entity names at x≈1 are not included in any pdfplumber table).

    Algorithm:
    1. Find "entity rows": lines where the first word is at the left edge and
       the row has at least min_data_cols words.
    2. Determine expected column count from the modal word count of entity rows
       (or use n_cols_override for sparse tables where modal < actual column count).
    3. Compute column starts as the MEDIAN x0 per position across entity rows with
       the exact expected word count — robust against right-aligned numbers.
    4. Reconstruct only the data section (rows within the y range of entity rows),
       merging extra words into the first column for multi-word entity names.
    5. Prepend col_names as the header row if provided.

    Extra params:
      word_x_min: if > 0, ignores words with x0 < word_x_min (isolates right-side column).
      word_x_max: if set, ignores words with x0 > word_x_max (strips right-side noise).
      y_tolerance: pixel bucket size for grouping words into visual lines (default 6).
        Increase to 8–10 when tasa values are rendered at a slightly different y than
        their corresponding entity/municipality words (e.g. suicidio municipality tables).
      n_cols_override: forces column count instead of using modal word count — useful
        for sparse tables where many rows have fewer values than the true column count.
      section_header_text: if set, finds the first row in sorted_lines whose first word
        starts with this text (e.g. 'Entidad' for "Entidad territorial IRA DNT"), then:
        (a) removes that row from entity_rows so it does not corrupt col_starts, and
        (b) anchors y_min to just below that row, excluding charts and other table
        sections that appear above the target data section on the same page.
      min_entity_len: minimum character length for the first word of an entity row.
        Use ≥4 to exclude single-char chart axis labels and 3-char column headers
        ('DNT', 'IRA', 'EDA') that appear at the left edge of chart figures.
      strict_page: if True, only try the specified page_idx (no fallback to adjacent
        pages). Use when other pages contain misleading tables that word_grid would
        otherwise pick up if the target page yields no result.
    """
    import pdfplumber
    import statistics as _stats

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n_pages = len(pdf.pages)
        pages = [page_idx] if strict_page else _pages_to_try(page_idx, n_pages)
        for p_idx in pages:
            page = pdf.pages[p_idx]
            words = page.extract_words(keep_blank_chars=False)
            if not words:
                continue

            # Optional: restrict words to an x window (removes out-of-column noise)
            if word_x_min > 0:
                words = [w for w in words if w['x0'] >= word_x_min]
            if word_x_max is not None:
                words = [w for w in words if w['x0'] <= word_x_max]

            # Group words into visual lines using greedy merging.
            # A word joins the current group if its top is within y_tolerance of the
            # group's first-word top.  Sorting by top first ensures that sub-pixel
            # offsets (e.g. tasa values ~0.8px below dept/mun names) always land in
            # the correct group regardless of rounding boundaries.
            words_by_top = sorted(words, key=lambda w: w['top'])
            line_groups: list[list] = []
            for w in words_by_top:
                if not line_groups or w['top'] - line_groups[-1][0]['top'] > y_tolerance:
                    line_groups.append([w])
                else:
                    line_groups[-1].append(w)
            sorted_lines = [
                (group[0]['top'], sorted(group, key=lambda w: w['x0']))
                for group in line_groups
            ]

            # Find entity rows: first word at left edge, enough columns, long enough name
            entity_rows = [
                (top, ws) for top, ws in sorted_lines
                if ws and ws[0]['x0'] <= entity_x_max and len(ws) >= min_data_cols
                and len(ws[0]['text']) >= min_entity_len
            ]
            if len(entity_rows) < 3:
                continue

            # Trim entity_rows to start from the known first data entity.
            # This prevents PDF column-header rows (e.g. "Entidad territorial IRA DNT")
            # from being used as reference rows for col_starts computation.
            if first_entity:
                start_idx = next(
                    (i for i, (_, ws) in enumerate(entity_rows)
                     if ws[0]['text'].startswith(first_entity)),
                    None,
                )
                if start_idx is not None:
                    entity_rows = entity_rows[start_idx:]

            # section_header_text: find the table section header in sorted_lines,
            # remove it from entity_rows (so it doesn't corrupt col_starts), and
            # record its y-position to override y_min later.
            # When section_header_text is required but not found on this page, skip
            # to the next candidate page (or give up if strict_page is True).
            section_header_top: float | None = None
            if section_header_text:
                for _top, _ws in sorted_lines:
                    if _ws and _ws[0]['text'].startswith(section_header_text):
                        section_header_top = _top
                        break
                if section_header_top is None:
                    continue
                entity_rows = [(t, ws) for t, ws in entity_rows
                               if not ws[0]['text'].startswith(section_header_text)]

            if len(entity_rows) < 2:
                continue

            # Column count: use override if provided (for sparse tables where modal
            # word count is lower than the true number of data columns)
            word_counts = [len(ws) for _, ws in entity_rows]
            if n_cols_override is not None:
                n_cols = n_cols_override
            else:
                n_cols = max(set(word_counts), key=word_counts.count)

            # Rows with exact word count → used for column position detection
            exact_rows = [(top, ws) for top, ws in entity_rows if len(ws) == n_cols]
            if len(exact_rows) < 2:
                exact_rows = entity_rows

            # Column starts: median x0 per position across exact-count rows
            col_starts: list[float] = []
            for i in range(n_cols):
                xs = [ws[i]['x0'] for _, ws in exact_rows if i < len(ws)]
                if xs:
                    col_starts.append(_stats.median(xs))
            n_cols = len(col_starts)

            if n_cols < min_data_cols:
                continue

            def assign_col(x0: float) -> int:
                # Scan right-to-left; return the first column whose left boundary
                # (midpoint between this and the previous column) is <= x0.
                for i in range(n_cols - 1, -1, -1):
                    left = (col_starts[i - 1] + col_starts[i]) / 2.0 if i > 0 else 0.0
                    if x0 >= left:
                        return i
                return 0

            # Reconstruct only the data section (skip header/footer).
            # y_min: normally from exact-count rows. When section_header_text is set,
            #   override with that header row's top + 1 — this correctly anchors the
            #   data section even when other page sections above have 4-word rows
            #   (same word count) that would otherwise corrupt y_min.
            # y_max: for sparse tables (n_cols_override set), use rows with word count
            #   in [min_data_cols, n_cols_override] — this captures all valid data rows
            #   (even those with fewer values than n_cols_override) while excluding
            #   footnote rows that have many more words than any data row.
            y_min = (section_header_top + 1) if section_header_top is not None \
                else min(top for top, _ in exact_rows)
            if n_cols_override is not None:
                valid_rows = [(t, ws) for t, ws in entity_rows
                              if min_data_cols <= len(ws) <= n_cols_override]
                y_max = max((top for top, _ in valid_rows), default=max(top for top, _ in exact_rows))
            else:
                y_max = max(top for top, _ in exact_rows)

            table: list[list[str]] = []
            min_filled = max(2, n_cols // 3)  # min non-empty cells to keep a row
            for top, ws in sorted_lines:
                if top < y_min or top > y_max + 8:
                    continue

                row: list[str] = [''] * n_cols

                if len(ws) <= n_cols:
                    # Normal row: assign each word to its column
                    for w in ws:
                        c = assign_col(w['x0'])
                        row[c] = (row[c] + ' ' + w['text']).strip()
                else:
                    # Extra words: multi-word entity name at left edge
                    # Collect entity-name words until a word reaches column 1
                    entity_parts: list[str] = [ws[0]['text']]
                    data_start = 1
                    for j in range(1, len(ws)):
                        if assign_col(ws[j]['x0']) >= 1:
                            data_start = j
                            break
                        entity_parts.append(ws[j]['text'])
                    row[0] = ' '.join(entity_parts)
                    for w in ws[data_start:]:
                        c = assign_col(w['x0'])
                        row[c] = (row[c] + ' ' + w['text']).strip()

                # Skip sparsely-filled rows (footnotes, legend entries)
                if sum(1 for c in row if c) >= min_filled:
                    table.append(row)

            if not table:
                continue

            # Prepend provided column names as header row
            if col_names:
                padded = list(col_names[:n_cols]) + [f'col_{i}' for i in range(len(col_names), n_cols)]
                table = [padded[:n_cols]] + table

            if len(table) >= 2:
                log.info(f'PDF [word-grid]: {len(table)} filas x {n_cols} cols en pag {p_idx}')
                return [table]

    return []


# --- Stage 3: Tesseract OCR ---

def _ocr_raw_tables(pdf_bytes: bytes, page_idx: int) -> list:
    """
    Rasterize one PDF page and extract table structure via Tesseract OCR.
    Returns a list of raw tables (list-of-list-of-str), compatible with _raw_to_dataframes.
    """
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        from pytesseract import Output
    except ImportError as e:
        log.debug(f'OCR dependencias no instaladas ({e}) — omitiendo Tesseract')
        return []

    try:
        images = convert_from_bytes(
            pdf_bytes,
            first_page=page_idx + 1,
            last_page=page_idx + 1,
            dpi=300,
        )
    except Exception as e:
        log.warning(f'OCR: pdf2image fallo en pag {page_idx} — {e}')
        return []

    if not images:
        return []

    try:
        data = pytesseract.image_to_data(
            images[0],
            lang='spa',
            output_type=Output.DICT,
            config='--psm 6 --oem 3',
        )
    except Exception as e:
        log.warning(f'OCR: Tesseract fallo — {e}')
        return []

    # Collect words with bounding boxes (filter low-confidence noise)
    words = []
    for i in range(len(data['text'])):
        text = str(data['text'][i]).strip()
        conf = int(data['conf'][i])
        if not text or conf < 25:
            continue
        left = int(data['left'][i])
        top = int(data['top'][i])
        width = int(data['width'][i])
        words.append((top, left, left + width, text))

    if not words:
        return []

    # Group into visual lines (words within 15px vertically)
    words.sort()
    lines: list[list[tuple]] = []
    cur: list[tuple] = [words[0]]
    for w in words[1:]:
        if abs(w[0] - cur[0][0]) <= 15:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x[1]))
            cur = [w]
    lines.append(sorted(cur, key=lambda x: x[1]))

    if len(lines) < 2:
        return []

    # Detect column separators: x-gaps >= 25px that no word spans
    max_x = max(w[2] for w in words)
    coverage = bytearray(max_x + 2)
    for _, left, right, _ in words:
        for x in range(left, min(right + 1, max_x + 1)):
            coverage[x] = 1

    # col_starts: left edge of each column
    col_starts = [0]
    in_gap = False
    gap_start = 0
    for x in range(max_x + 1):
        if not coverage[x]:
            if not in_gap:
                in_gap = True
                gap_start = x
        else:
            if in_gap:
                if x - gap_start >= 25:
                    col_starts.append(x)
                in_gap = False
    col_starts.append(max_x + 1)
    n_cols = len(col_starts) - 1

    def _assign_col(left: int) -> int:
        for c in range(n_cols - 1, -1, -1):
            if left >= col_starts[c]:
                return c
        return 0

    # Build raw table rows
    table: list[list[str]] = []
    for line in lines:
        row = [''] * n_cols
        for top, left, right, text in line:
            c = _assign_col(left)
            row[c] = (row[c] + ' ' + text).strip()
        if any(cell for cell in row):
            table.append(row)

    if len(table) < 2:
        return []

    log.info(f'OCR: {len(table)} filas x {n_cols} columnas extraidas de pag {page_idx}')
    return [table]


# --- Orchestrator ---

def _find_table_by_header(raw_tables: list, header_match: list[str]) -> int | None:
    """Return index of first table whose header row starts with given strings."""
    for i, table in enumerate(raw_tables):
        if not table:
            continue
        header = table[0]
        match = all(
            j < len(header) and (header[j] or '').startswith(header_match[j])
            for j in range(len(header_match))
        )
        if match:
            return i
    return None


def _extract_tables_from_pdf(pdf_bytes: bytes, page_idx: int,
                              table_indices: list[int],
                              strategy: str = 'auto',
                              col_names: list[str] | None = None,
                              word_grid_options: dict | None = None,
                              table_header_match: list[str] | None = None) -> list[pl.DataFrame]:
    """
    Extract tables from a PDF page using a 4-stage fallback pipeline:
      1. pdfplumber (lines strategy)  — PDFs with ruling lines
      2. pdfplumber (word-grid)       — borderless/fragmented layouts
      3. pdfplumber (text strategy)   — whitespace-separated columns
      4. Tesseract OCR                — image-based PDFs

    strategy:
      'auto'       — try all stages in order (default)
      'word_grid'  — skip lines strategy, go straight to word-grid
      'text'       — skip lines + word-grid, go straight to pdfplumber text strategy
                     (use when lines strategy finds wrong bordered tables on the same page)
    """
    def _resolve_indices(raw_tables):
        if table_header_match:
            found = _find_table_by_header(raw_tables, table_header_match)
            return [found] if found is not None else []
        return table_indices

    # Stage 1: pdfplumber lines (skipped when strategy='word_grid' or 'text')
    if strategy not in ('word_grid', 'text'):
        try:
            raw_tables, _ = _pdfplumber_tables(pdf_bytes, page_idx, strategy='lines')
            if raw_tables:
                indices = _resolve_indices(raw_tables)
                if table_header_match and not indices:
                    # Header match required but not found — this PDF/period has no such table
                    return []
                results = _raw_to_dataframes(raw_tables, indices)
                if results:
                    return results
        except Exception as e:
            log.debug(f'pdfplumber (lines) fallo: {e}')

    # When table_header_match is set, only the lines strategy is authoritative.
    # Falling through to word-grid/text/OCR would extract wrong tables.
    if table_header_match:
        return []

    # Stage 2: word-grid reconstruction (skipped when strategy='text')
    if strategy != 'text':
        try:
            wg_kwargs = word_grid_options or {}
            raw_tables = _pdfplumber_word_grid(pdf_bytes, page_idx, col_names=col_names, **wg_kwargs)
            if raw_tables:
                results = _raw_to_dataframes(raw_tables, list(range(len(raw_tables))))
                if results:
                    log.info(f'PDF: tablas extraidas con word-grid (pag {page_idx})')
                    return results
        except Exception as e:
            log.debug(f'word-grid fallo: {e}')

    # Stage 3: pdfplumber text strategy (skipped when strategy='word_grid')
    if strategy != 'word_grid':
        try:
            raw_tables, _ = _pdfplumber_tables(pdf_bytes, page_idx, strategy='text')
            if raw_tables:
                results = _raw_to_dataframes(raw_tables, _resolve_indices(raw_tables))
                if results:
                    log.info(f'PDF: tablas extraidas con estrategia text (pag {page_idx})')
                    return results
        except Exception as e:
            log.debug(f'pdfplumber (text) fallo: {e}')

    # Stage 4: Tesseract OCR (skipped when strategy='word_grid')
    if strategy != 'word_grid':
        try:
            raw_tables = _ocr_raw_tables(pdf_bytes, page_idx)
            if raw_tables:
                results = _raw_to_dataframes(raw_tables, _resolve_indices(raw_tables))
                if results:
                    log.info(f'PDF: tablas extraidas con Tesseract OCR (pag {page_idx})')
                    return results
        except Exception as e:
            log.debug(f'Tesseract fallo: {e}')

    return []


# ---------------------------------------------------------------------------
# Per-event, per-period scraper
# ---------------------------------------------------------------------------

def _geo_match_rate(df: pl.DataFrame, col: str, threshold: float = 0.30) -> bool:
    """Return True if ≥threshold fraction of non-empty values in col are Colombian departments."""
    if col not in df.columns:
        return True  # no validation column — accept by default
    vals = df[col].drop_nulls().cast(pl.Utf8).to_list()
    vals = [v.strip() for v in vals if v.strip()]
    if not vals:
        return False
    import unicodedata as _ud, re as _re

    def _norm(s: str) -> str:
        s = s.upper().strip()
        s = _ud.normalize('NFD', s)
        s = ''.join(c for c in s if _ud.category(c) != 'Mn')
        s = _re.sub(r'[^A-Z0-9 ]', ' ', s)
        return _re.sub(r'\s+', ' ', s).strip()

    matched = sum(1 for v in vals if _norm(v) in _COLOMBIA_DEPARTMENTS)
    return (matched / len(vals)) >= threshold


def scrape_event_period(event: dict, parquet_dir: Path,
                        pe: int, year: int) -> list[Path]:
    """
    Download and parse one INS PDF for (event, pe, year).
    Returns list of parquet paths written (empty if not available or already cached).
    """
    key = event['key']
    roman = ROMAN[pe - 1]
    stamp = f'PE_{roman}_{year}'

    # Cache check: any parquet for this stamp already exists?
    existing = sorted(parquet_dir.glob(f'ins_{key}_{stamp}*.parquet'))
    if existing:
        log.debug(f'INS [{key}] {stamp}: cache OK ({len(existing)} archivo(s))')
        return existing

    # Build URL candidates (primary name + variants)
    url_names = [event['url_name']] + URL_NAME_VARIANTS.get(key, [])

    pdf_bytes = None
    for name in url_names:
        url = _build_url(name, roman, year)
        log.debug(f'INS [{key}]: intentando {url}')
        pdf_bytes = _download_pdf(url)
        if pdf_bytes:
            break

    if not pdf_bytes:
        return []

    def _try_extract(page_idx: int) -> list[pl.DataFrame]:
        return _extract_tables_from_pdf(
            pdf_bytes, page_idx, event.get('tables', [0]),
            strategy=event.get('strategy', 'auto'),
            col_names=event.get('column_names'),
            word_grid_options=event.get('word_grid_options'),
            table_header_match=event.get('table_header_match'),
        )

    def _apply_schema(raw_tables: list[pl.DataFrame]) -> list[pl.DataFrame]:
        column_schema = event.get('column_schema', [])
        if not column_schema:
            return raw_tables
        renamed = []
        for i, df in enumerate(raw_tables):
            if i < len(column_schema) and column_schema[i]:
                target = column_schema[i]
                # Use positional select (pl.nth) to avoid rename conflicts when the
                # source df already has a column named like a target column at a
                # different position (e.g. 'municipio' at index 2 while target[1]='municipio').
                n = min(len(df.columns), len(target))
                df = df.select([pl.nth(j).alias(target[j]) for j in range(n)])
            renamed.append(df)
        return renamed

    geo_col = event.get('geo_validate_col')
    min_rows = event.get('min_entity_rows', 0)

    def _table_ok(df: pl.DataFrame) -> bool:
        if min_rows and len(df) < min_rows:
            return False
        return not geo_col or _geo_match_rate(df, geo_col)

    # Main extraction — failures set tables=[] but do NOT return early so that
    # extra_tables (e.g. a supplementary page) can still be processed.
    _main = _try_extract(event['page'])
    if not _main:
        log.warning(f'INS [{key}] {stamp}: pag {event["page"]} sin tablas extraibles')
        tables = []
    else:
        tables = _apply_schema(_main)
        if geo_col or min_rows:
            filtered = [df for df in tables if _table_ok(df)]
            if len(filtered) < len(tables):
                dropped = len(tables) - len(filtered)
                log.info(f'INS [{key}] {stamp}: {dropped} tabla(s) descartadas (geo/min_rows)')
            if filtered:
                tables = filtered
            else:
                log.info(f'INS [{key}] {stamp}: pag {event["page"]} sin tablas válidas — probando páginas alternativas')
                tables = []
                for alt_page in event.get('fallback_pages', []):
                    alt = _apply_schema(_try_extract(alt_page))
                    alt_valid = [df for df in alt if _table_ok(df)]
                    if alt_valid:
                        log.info(f'INS [{key}] {stamp}: datos válidos encontrados en pag {alt_page}')
                        tables = alt_valid
                        break
                if not tables:
                    log.warning(f'INS [{key}] {stamp}: no se encontraron tablas válidas en ninguna página')

    # Extra table extractions — always attempted if PDF was downloaded successfully.
    # Results are appended to tables and written as separate parquet files.
    for extra_cfg in event.get('extra_tables', []):
        extra_dfs = _extract_tables_from_pdf(
            pdf_bytes,
            extra_cfg['page'],
            extra_cfg.get('tables', [0]),
            strategy=extra_cfg.get('strategy', 'auto'),
            col_names=extra_cfg.get('column_names'),
            word_grid_options=extra_cfg.get('word_grid_options'),
        )
        extra_geo_col = extra_cfg.get('geo_validate_col')
        col_schema = extra_cfg.get('column_schema', [])
        for i, edf in enumerate(extra_dfs):
            if i < len(col_schema) and col_schema[i]:
                target = col_schema[i]
                n = min(len(edf.columns), len(target))
                edf = edf.select([pl.nth(j).alias(target[j]) for j in range(n)])
            if extra_geo_col and not _geo_match_rate(edf, extra_geo_col):
                log.info(f'INS [{key}] {stamp}: extra_table pag {extra_cfg["page"]} rechazada (geo)')
                continue
            tables.append(edf)

    if not tables:
        return []

    # Trim rows that appear before the known first data entity (e.g. header fragments)
    first_entity = event.get('first_entity')
    if first_entity:
        trimmed = []
        for df in tables:
            col0 = df.columns[0]
            mask = df[col0].str.starts_with(first_entity)
            idxs = mask.arg_true()
            if len(idxs) > 0:
                df = df.slice(idxs[0])
            trimmed.append(df)
        tables = trimmed

    table_labels = event.get('table_labels', [])

    written = []
    for i, df in enumerate(tables):
        extra = [
            pl.lit(year).alias('anio'),
            pl.lit(roman).alias('periodo_epidemiologico'),
            pl.lit(key).alias('evento'),
        ]
        if i < len(table_labels):
            extra.append(pl.lit(table_labels[i]).alias('poblacion_categoria'))
        df = df.with_columns(extra)
        suffix = f'_tabla{i}' if len(tables) > 1 else ''
        fpath = parquet_dir / f'ins_{key}_{stamp}{suffix}.parquet'
        df.write_parquet(fpath, compression='zstd')
        log.info(f'INS [{key}]: {fpath.name} ({len(df):,} filas)')
        written.append(fpath)

    return written


# ---------------------------------------------------------------------------
# DuckDB registration
# ---------------------------------------------------------------------------

def _register_duckdb(parquet_dir: Path, db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    for event in EVENTS:
        key = event['key']
        files = sorted(parquet_dir.glob(f'ins_{key}_*.parquet'))
        if not files:
            continue
        glob = f'{parquet_dir.as_posix()}/ins_{key}_*.parquet'
        table = f'ins_{key}'
        con.execute(f'DROP TABLE IF EXISTS {table}')
        con.execute(
            f"CREATE TABLE {table} AS "
            f"SELECT * FROM read_parquet('{glob}', union_by_name=True)"
        )
        n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'  DuckDB [{table}]: {n:,} filas')
    con.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(base_dir: str = None, events: list[str] | None = None,
        start_year: int = START_YEAR) -> None:
    """
    Args:
        base_dir:   project root
        events:     list of event keys to scrape (None = all)
        start_year: first year to scrape (default START_YEAR)
    """
    base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    parquet_dir = base_dir / 'data' / 'parquet'
    db_path = base_dir / 'data' / 'informe_regional.duckdb'
    parquet_dir.mkdir(parents=True, exist_ok=True)

    selected = [e for e in EVENTS if events is None or e['key'] in events]
    periods = _all_periods(start_year)

    print(f'ins_pdf_scraper: {len(periods)} periodos desde PE I {start_year} hasta PE actual')

    all_written = []
    for event in selected:
        key = event['key']
        new_for_event = 0
        for pe, year in periods:
            written = scrape_event_period(event, parquet_dir, pe, year)
            if written:
                # Only count truly new files (not from cache)
                new_files = [p for p in written
                             if not any(p == x for x in sorted(parquet_dir.glob(
                                 f'ins_{key}_PE_{ROMAN[pe-1]}_{year}*.parquet'
                             )) if x not in written)]
                all_written.extend(written)
                new_for_event += len([p for p in written])
        if new_for_event > 0:
            print(f'  [{key}]: {new_for_event} archivo(s) disponibles')

    _register_duckdb(parquet_dir, db_path)

    if not all_written:
        print('ins_pdf_scraper: ADVERTENCIA — no se generaron archivos nuevos')
    else:
        print(f'ins_pdf_scraper OK')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
