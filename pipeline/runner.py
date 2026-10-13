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
  1  some scrapers failed; transform rebuilt the DB with the sources that did refresh
  2  transform failed; the DB was not rebuilt
"""

import argparse
import logging
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
import scrapers.ins_pdf_scraper as ins_pdf
import pipeline.transform as transform
from scrapers.errors import ScrapeError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)


# Exit codes for the one-shot modes (scripts/run_monthly_pipeline.sh relies on them)
EXIT_OK = 0
EXIT_PARTIAL = 1        # some scrapers failed; transform rebuilt the DB with what it had
EXIT_TRANSFORM = 2      # transform failed; the DB was not rebuilt


def _safe(fn, name: str) -> bool:
    """Run one pipeline step; return True on success. Never raises."""
    try:
        log.info(f'>>> Iniciando: {name}')
        fn(base_dir=str(BASE_DIR))
        log.info(f'<<< Completado: {name}')
        return True
    except ScrapeError as e:
        log.error(f'!!! Falló {name}: {e}')
    except Exception:
        log.error(f'!!! Error en {name}:\n{traceback.format_exc()}')
    return False


def _run_steps(title: str, steps: list[tuple]) -> int:
    """Run (fn, name) steps in order and return an exit code.

    A failed scraper doesn't stop the others, and transform still runs so every
    source that did refresh gets published.
    """
    log.info(f'=== {title} ===')
    results = {name: _safe(fn, name) for fn, name in steps}
    failed = [name for name, ok in results.items() if not ok]

    log.info(f'=== {title}: resumen ===')
    for name, ok in results.items():
        log.info(f'  {"OK   " if ok else "FALLO"}  {name}')
    if 'transform' in failed:
        log.error(f'=== {title}: FALLÓ transform — la base de datos no se reconstruyó ===')
        return EXIT_TRANSFORM
    if failed:
        log.warning(f'=== {title}: completado con {len(failed)} fallo(s): {", ".join(failed)} ===')
        return EXIT_PARTIAL
    log.info(f'=== {title}: completado sin fallos ===')
    return EXIT_OK


def run_monthly() -> int:
    return _run_steps('Ciclo mensual', [
        (reps.run, 'reps_scraper'),            # all 6 REPS endpoints
        (irca.run, 'irca_scraper'),
        (afiliacion.run, 'afiliacion_scraper'),
        (supersalud.run, 'supersalud_scraper'),
        (ins_pdf.run, 'ins_pdf_scraper'),
        (transform.run, 'transform'),
    ])


def run_annual() -> int:
    return _run_steps('Ciclo anual (demografía)', [
        (demografico.run, 'demografico'),
        (transform.run, 'transform'),
    ])


def run_all() -> int:
    return _run_steps('Ejecución completa', [
        (demografico.run, 'demografico'),
        (reps.run, 'reps_scraper'),
        (irca.run, 'irca_scraper'),
        (afiliacion.run, 'afiliacion_scraper'),
        (supersalud.run, 'supersalud_scraper'),
        (ins_pdf.run, 'ins_pdf_scraper'),
        (transform.run, 'transform'),
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
        sys.exit(_run_steps('Solo transform', [(transform.run, 'transform')]))

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
