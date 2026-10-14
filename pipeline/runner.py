# -*- coding: utf-8 -*-
"""
runner.py — Orchestrador APScheduler para el pipeline de datos.

Schedules:
  - 5th of each month at 08:00: REPS IPS + IRCA + Afiliación + transform
  - July 15 at 08:00: DANE demographics + transform

Usage:
  python pipeline/runner.py            # start scheduler (blocking)
  python pipeline/runner.py --run-now  # run all scrapers immediately then exit

Exit codes (one-shot modes):
  0  every step succeeded
  1  some scrapers failed; a new DB was still built, checked and published
  2  transform, quality checks or publish failed; the live DB was NOT replaced

transform builds into data/informe_regional.build.duckdb; the quality checks run
on that file and only if they pass is it renamed over data/informe_regional.duckdb.
"""

import argparse
import faulthandler
import logging
import os
import shutil
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from apscheduler.schedulers.blocking import BlockingScheduler

import scrapers.demografico as demografico
# import scrapers.reps_ips_scraper as reps_ips  # legacy — use reps_scraper instead
import scrapers.reps_scraper as reps           # multi-endpoint (all 6 REPS queries)
import scrapers.irca_scraper as irca
import scrapers.afiliacion_scraper as afiliacion
import scrapers.supersalud_scraper as supersalud
import scrapers.bdua_scraper as bdua
import scrapers.sivigila_scraper as sivigila
import scrapers.cuipo_scraper as cuipo
import scrapers.sicodis_scraper as sicodis
import scrapers.ins_pdf_scraper as ins_pdf
import pipeline.transform as transform
import pipeline.quality as quality
from scrapers.errors import ScrapeError
from pipeline.quality import QualityError

# A native crash (segfault in a C extension) kills the process before any
# Python handler runs. faulthandler writes the crashing stack to stderr, which
# the cron script captures in the log, and line buffering keeps the prints that
# preceded it (a crash on 2026-10-13 left only the first log line).
faulthandler.enable()
sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)


# Exit codes for the one-shot modes (scripts/run_monthly_pipeline.sh relies on them)
EXIT_OK = 0
EXIT_PARTIAL = 1        # some scrapers failed; a new DB was still built, checked and published
EXIT_NOT_PUBLISHED = 2  # transform, quality checks or publish failed; the live DB is unchanged

LIVE_DB = BASE_DIR / 'data' / 'informe_regional.duckdb'
BUILD_DB = BASE_DIR / 'data' / 'informe_regional.build.duckdb'

# Steps that produce the new DB; 'publicar' only runs if all of them succeeded
_BUILD_STEPS = ('transform', 'calidad')


def _safe(fn, name: str) -> bool:
    """Run one pipeline step; return True on success. Never raises."""
    try:
        log.info(f'>>> Iniciando: {name}')
        fn(base_dir=str(BASE_DIR))
        log.info(f'<<< Completado: {name}')
        return True
    except (ScrapeError, QualityError) as e:
        log.error(f'!!! Falló {name}: {e}')
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        # BaseException, not Exception: a Rust panic inside polars/duckdb surfaces
        # as pyo3 PanicException (a BaseException) and would otherwise abort the
        # whole run instead of failing just this step.
        log.error(f'!!! Error en {name}:\n{traceback.format_exc()}')
    return False


# ── Build → check → publish ──────────────────────────────────────────────────
# transform writes to a separate build file, the quality checks run on it, and
# only then is it moved over the live DB in one atomic rename. A failed run
# never leaves the dashboard reading a half-built or unchecked database.

def _transform_step(base_dir: str) -> None:
    # Start from the live DB so the history tables (_carga_log,
    # _calidad_resultados) carry over; transform rebuilds everything else.
    BUILD_DB.unlink(missing_ok=True)
    Path(f'{BUILD_DB}.wal').unlink(missing_ok=True)
    if LIVE_DB.exists():
        shutil.copy2(LIVE_DB, BUILD_DB)
    transform.run(base_dir, db_path=BUILD_DB)


def _quality_step(base_dir: str) -> None:
    quality.run(base_dir, db_path=BUILD_DB)


def _publish_step(base_dir: str) -> None:
    if Path(f'{BUILD_DB}.wal').exists():
        raise RuntimeError(f'{BUILD_DB}.wal existe: el DB de build no se cerró limpio')
    # os.replace is atomic on the same filesystem. On Windows it fails while
    # another process (e.g. a local Streamlit) holds the live file open.
    os.replace(BUILD_DB, LIVE_DB)
    log.info(f'DB publicado: {LIVE_DB}')


_BUILD_AND_PUBLISH = [
    (_transform_step, 'transform'),
    (_quality_step, 'calidad'),
    (_publish_step, 'publicar'),
]


def _run_steps(title: str, steps: list[tuple]) -> int:
    """Run (fn, name) steps in order and return an exit code.

    A failed scraper doesn't stop the others; transform still runs so every
    source that did refresh gets published. 'publicar' is skipped unless every
    build step succeeded.
    """
    log.info(f'=== {title} ===')
    results: dict[str, bool] = {}
    for fn, name in steps:
        if name == 'publicar' and not all(results.get(s, True) for s in _BUILD_STEPS):
            log.error('!!! Falló publicar: omitido — el DB nuevo no pasó transform/calidad; '
                      f'se conserva el DB anterior. Build para inspección: {BUILD_DB}')
            results[name] = False
            continue
        results[name] = _safe(fn, name)
    failed = [name for name, ok in results.items() if not ok]

    log.info(f'=== {title}: resumen ===')
    for name, ok in results.items():
        log.info(f'  {"OK   " if ok else "FALLO"}  {name}')
    if any(s in failed for s in (*_BUILD_STEPS, 'publicar')):
        log.error(f'=== {title}: NO se publicó un DB nuevo — el dashboard sigue con los datos anteriores ===')
        return EXIT_NOT_PUBLISHED
    if failed:
        log.warning(f'=== {title}: publicado, con {len(failed)} fallo(s): {", ".join(failed)} ===')
        return EXIT_PARTIAL
    log.info(f'=== {title}: completado sin fallos ===')
    return EXIT_OK


def run_monthly() -> int:
    return _run_steps('Ciclo mensual', [
        (reps.run, 'reps_scraper'),            # all 6 REPS endpoints
        (irca.run, 'irca_scraper'),
        (afiliacion.run, 'afiliacion_scraper'),
        (supersalud.run, 'supersalud_scraper'),
        (bdua.run, 'bdua_scraper'),            # monthly snapshot: archive every run
        (sivigila.run, 'sivigila_scraper'),    # annual files; cheap no-op when unchanged
        (cuipo.run, 'cuipo_scraper'),          # quarterly; refetches only when CGR updates
        (sicodis.run, 'sicodis_scraper'),      # SGP allocations; current year each run
        (ins_pdf.run, 'ins_pdf_scraper'),
        *_BUILD_AND_PUBLISH,
    ])


def run_annual() -> int:
    return _run_steps('Ciclo anual (demografía)', [
        (demografico.run, 'demografico'),
        *_BUILD_AND_PUBLISH,
    ])


def run_all() -> int:
    return _run_steps('Ejecución completa', [
        (demografico.run, 'demografico'),
        (reps.run, 'reps_scraper'),
        (irca.run, 'irca_scraper'),
        (afiliacion.run, 'afiliacion_scraper'),
        (supersalud.run, 'supersalud_scraper'),
        (bdua.run, 'bdua_scraper'),            # monthly snapshot: archive every run
        (sivigila.run, 'sivigila_scraper'),    # annual files; cheap no-op when unchanged
        (cuipo.run, 'cuipo_scraper'),          # quarterly; refetches only when CGR updates
        (sicodis.run, 'sicodis_scraper'),      # SGP allocations; current year each run
        (ins_pdf.run, 'ins_pdf_scraper'),
        *_BUILD_AND_PUBLISH,
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description='Pipeline Informe Regional — runner')
    parser.add_argument('--run-now', action='store_true',
                        help='Ejecutar todos los scrapers inmediatamente y salir')
    parser.add_argument('--monthly', action='store_true',
                        help='Ejecutar solo el ciclo mensual y salir')
    parser.add_argument('--annual', action='store_true',
                        help='Ejecutar solo el ciclo anual (demografía) y salir')
    parser.add_argument('--transform-only', action='store_true',
                        help='Solo ejecutar transform (sin scrapers) y salir')
    args = parser.parse_args()

    if args.run_now:
        sys.exit(run_all())
    if args.monthly:
        sys.exit(run_monthly())
    if args.annual:
        sys.exit(run_annual())
    if args.transform_only:
        sys.exit(_run_steps('Solo transform', _BUILD_AND_PUBLISH))

    # Scheduled mode
    scheduler = BlockingScheduler(timezone='America/Bogota')

    # Monthly: 5th at 08:00
    # misfire_grace_time: still run if the process was busy/asleep at the trigger
    # time (APScheduler's default is 1 s, which silently skips the month).
    scheduler.add_job(run_monthly, 'cron', day=5, hour=8, minute=0,
                      id='monthly_refresh', name='Ciclo mensual (IPS + IRCA + Afiliación)',
                      misfire_grace_time=6 * 3600, coalesce=True)

    # Annual: July 15 at 08:00
    scheduler.add_job(run_annual, 'cron', month=7, day=15, hour=8, minute=0,
                      id='annual_refresh', name='Ciclo anual (Demografía DANE)',
                      misfire_grace_time=6 * 3600, coalesce=True)

    log.info('Scheduler iniciado. Trabajos programados:')
    for job in scheduler.get_jobs():
        log.info(f'  [{job.id}] {job.name} — próxima ejecución: {job.next_run_time}')
    log.info('Presiona Ctrl+C para detener.')

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info('Scheduler detenido.')


if __name__ == '__main__':
    main()
