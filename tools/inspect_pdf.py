# -*- coding: utf-8 -*-
"""
PDF Inspection Tool — INS event reports.

Scans every page of a downloaded INS PDF and reports what tables are found
using each extraction method (pdfplumber lines, pdfplumber text, Tesseract OCR).
Use this to find/verify the correct page and table indices for each event.

Usage:
    # Inspect a specific event and period:
    .venv/Scripts/python tools/inspect_pdf.py --event mortalidad_materna --pe IV --year 2025

    # Scan all events for PE III 2025:
    .venv/Scripts/python tools/inspect_pdf.py --pe III --year 2025

    # Use a local PDF file:
    .venv/Scripts/python tools/inspect_pdf.py --file path/to/report.pdf

    # List available event keys:
    .venv/Scripts/python tools/inspect_pdf.py --list
"""

import argparse
import io
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests

# Add project root to path so we can import scrapers
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.ins_pdf_scraper import (
    EVENTS,
    ROMAN,
    URL_NAME_VARIANTS,
    _build_url,
    _download_pdf,
    _normalize_col,
    _ocr_raw_tables,
    _pdfplumber_tables,
    _raw_to_dataframes,
)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _separator(char='-', width=72):
    return char * width


def _print_raw_table_preview(raw_table, max_rows=5, label=''):
    if not raw_table:
        print('    (vacia)')
        return
    if label:
        print(f'    [{label}]')
    header = raw_table[0]
    print(f'    Encabezado: {header}')
    for i, row in enumerate(raw_table[1:max_rows + 1], 1):
        print(f'    Fila {i:2d}: {row}')
    if len(raw_table) - 1 > max_rows:
        print(f'    ... ({len(raw_table) - 1} filas en total)')


def _scan_page_pdfplumber(pdf_bytes: bytes, page_idx: int) -> dict:
    """Scan a single page with both pdfplumber strategies. Returns dict of results."""
    result = {'lines': [], 'text': []}
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if page_idx >= len(pdf.pages):
                return result
            page = pdf.pages[page_idx]

            # Lines strategy
            try:
                tables = page.extract_tables()
                result['lines'] = tables or []
            except Exception as e:
                result['lines_error'] = str(e)

            # Text strategy
            try:
                tables = page.extract_tables({
                    'vertical_strategy': 'text',
                    'horizontal_strategy': 'text',
                    'min_words_vertical': 3,
                    'min_words_horizontal': 1,
                })
                result['text'] = tables or []
            except Exception as e:
                result['text_error'] = str(e)

            # Basic stats about the page
            result['word_count'] = len(page.extract_words())
    except Exception as e:
        result['error'] = str(e)
    return result


def _scan_page_ocr(pdf_bytes: bytes, page_idx: int) -> list:
    """Scan a page with Tesseract OCR. Returns raw tables."""
    try:
        return _ocr_raw_tables(pdf_bytes, page_idx)
    except Exception as e:
        print(f'    OCR error: {e}')
        return []


def _count_pages(pdf_bytes: bytes) -> int:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Main inspection logic
# ---------------------------------------------------------------------------

def inspect_pdf(pdf_bytes: bytes, event_key: str = '',
                use_ocr: bool = False, full_scan: bool = True,
                known_page: int | None = None, known_tables: list | None = None):
    """
    Scan all pages of a PDF and report found tables.
    If known_page/known_tables are provided, also shows the configured extraction result.
    """
    n_pages = _count_pages(pdf_bytes)
    print(f'\nPDF: {n_pages} paginas')
    print(_separator())

    pages_to_scan = range(n_pages) if full_scan else ([known_page] if known_page is not None else range(n_pages))

    found_anything: dict[int, dict] = {}

    for p_idx in pages_to_scan:
        result = _scan_page_pdfplumber(pdf_bytes, p_idx)
        n_lines = len(result.get('lines', []))
        n_text = len(result.get('text', []))
        words = result.get('word_count', 0)

        if n_lines == 0 and n_text == 0 and words < 10:
            continue  # skip nearly empty pages

        marker = ' <-- CONFIGURADO' if known_page is not None and p_idx == known_page else ''
        print(f'\nPagina {p_idx} (#{p_idx + 1}){marker}  [{words} palabras]')

        # Lines strategy
        if n_lines:
            print(f'  pdfplumber [lines]: {n_lines} tabla(s)')
            for t_idx, tbl in enumerate(result['lines']):
                n_rows = len(tbl)
                n_cols = len(tbl[0]) if tbl else 0
                is_configured = (known_page == p_idx and known_tables and t_idx in known_tables)
                cfg_marker = ' <-- TABLA CONFIGURADA' if is_configured else ''
                print(f'    Tabla {t_idx}: {n_rows} filas x {n_cols} columnas{cfg_marker}')
                _print_raw_table_preview(tbl, max_rows=3)
            found_anything[p_idx] = result
        else:
            if result.get('lines_error'):
                print(f'  pdfplumber [lines]: ERROR — {result["lines_error"]}')
            else:
                print(f'  pdfplumber [lines]: sin tablas')

        # Text strategy (only show if different from lines)
        if n_text and n_text != n_lines:
            print(f'  pdfplumber [text]:  {n_text} tabla(s)')
            for t_idx, tbl in enumerate(result['text']):
                n_rows = len(tbl)
                n_cols = len(tbl[0]) if tbl else 0
                print(f'    Tabla {t_idx}: {n_rows} filas x {n_cols} columnas')
                _print_raw_table_preview(tbl, max_rows=2)
            found_anything[p_idx] = result
        elif n_text == 0 and n_lines == 0:
            print(f'  pdfplumber [text]:  sin tablas')

        # OCR (optional, only when pdfplumber found nothing or explicitly requested)
        if use_ocr and n_lines == 0 and n_text == 0:
            print(f'  Tesseract OCR:')
            ocr_tables = _scan_page_ocr(pdf_bytes, p_idx)
            if ocr_tables:
                for t_idx, tbl in enumerate(ocr_tables):
                    n_rows = len(tbl)
                    n_cols = len(tbl[0]) if tbl else 0
                    print(f'    Tabla {t_idx}: {n_rows} filas x {n_cols} columnas')
                    _print_raw_table_preview(tbl, max_rows=2)
                found_anything[p_idx] = {'ocr': ocr_tables}
            else:
                print(f'    sin tablas')

    # Summary
    print(f'\n{_separator()}')
    if found_anything:
        print('RESUMEN - paginas con tablas:')
        for p_idx, res in sorted(found_anything.items()):
            n = len(res.get('lines') or res.get('ocr') or [])
            marker = ' <-- CONFIGURADA' if known_page == p_idx else ''
            print(f'  Pagina {p_idx} (#{p_idx + 1}): {n} tabla(s){marker}')

        # Show config suggestion only when no known config exists
        if event_key and known_page is None:
            # Pick the page with the most lines-strategy tables
            best_page = max(
                found_anything.keys(),
                key=lambda p: len(found_anything[p].get('lines') or [])
            )
            best_tables = found_anything[best_page].get('lines', found_anything[best_page].get('ocr', []))
            n_tables = len(best_tables)
            print(f'\nSugerencia de configuracion para [{event_key}] en ins_pdf_scraper.py:')
            print(f"    {{'key': '{event_key}',")
            print(f"     'page': {best_page},   # pagina #{best_page + 1}")
            print(f"     'tables': {list(range(n_tables))},")
            print(f"    }}")
        elif known_page is not None:
            print(f'\nConfiguracion actual correcta: page={known_page}, tables={known_tables}')
    else:
        print('No se encontraron tablas en ninguna pagina.')
        if not use_ocr:
            print('Intenta con --ocr para usar Tesseract en paginas sin tablas vectoriales.')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Inspect INS PDF tables to verify event configuration.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--event', help='Event key (e.g. mortalidad_materna)')
    parser.add_argument('--pe', help='Roman numeral period (e.g. III)', default='III')
    parser.add_argument('--year', type=int, help='Year (e.g. 2025)', default=2025)
    parser.add_argument('--file', help='Path to local PDF file (skips download)')
    parser.add_argument('--ocr', action='store_true', help='Use Tesseract OCR on pages with no vector tables')
    parser.add_argument('--page', type=int, help='Only scan this page (0-indexed)', default=None)
    parser.add_argument('--list', action='store_true', help='List available event keys and exit')
    args = parser.parse_args()

    if args.list:
        print('Available event keys:')
        for e in EVENTS:
            print(f"  {e['key']:30s}  page={e['page']}  tables={e['tables']}")
        return

    # Load PDF
    if args.file:
        pdf_path = Path(args.file)
        if not pdf_path.exists():
            print(f'ERROR: archivo no encontrado: {args.file}')
            sys.exit(1)
        pdf_bytes = pdf_path.read_bytes()
        print(f'PDF local: {pdf_path}')
        event_key = args.event or ''
        known_page = None
        known_tables = None
    elif args.event:
        # Find event config
        event = next((e for e in EVENTS if e['key'] == args.event), None)
        if event is None:
            print(f'ERROR: evento "{args.event}" no encontrado. Usa --list para ver opciones.')
            sys.exit(1)

        event_key = event['key']
        known_page = event['page']
        known_tables = event['tables']
        roman = args.pe.upper()

        url_names = [event['url_name']] + URL_NAME_VARIANTS.get(event_key, [])
        pdf_bytes = None
        for name in url_names:
            url = _build_url(name, roman, args.year)
            print(f'Descargando: {url}')
            pdf_bytes = _download_pdf(url)
            if pdf_bytes:
                print(f'Descarga OK ({len(pdf_bytes):,} bytes)')
                break
        if not pdf_bytes:
            print(f'ERROR: no se pudo descargar PDF para [{event_key}] PE {roman} {args.year}')
            sys.exit(1)
    else:
        parser.print_help()
        print('\nERROR: debes indicar --event o --file')
        sys.exit(1)

    # Run inspection
    full_scan = args.page is None
    page_to_use = args.page if args.page is not None else (known_page if known_page is not None else None)
    inspect_pdf(
        pdf_bytes,
        event_key=event_key,
        use_ocr=args.ocr,
        full_scan=full_scan,
        known_page=known_page,
        known_tables=known_tables,
    )


if __name__ == '__main__':
    main()
