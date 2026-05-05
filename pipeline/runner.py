# -*- coding: utf-8 -*-
"""
runner.py — Orchestrador APScheduler para el pipeline de datos.

Schedules:
  - 5th of each month at 08:00: REPS IPS + IRCA + Afiliación + transform
  - July 15 at 08:00: DANE demographics + transform

Usage:
  python pipeline/runner.py            # start scheduler (blocking)
  python pipeline/runner.py --run-now  # run all scrapers immediately then exit
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)


def _safe(fn, name: str) -> None:
    try:
        log.info(f'>>> Iniciando: {name}')
        fn(base_dir=str(BASE_DIR))
        log.info(f'<<< Completado: {name}')
    except Exception:
        log.error(f'!!! Error en {name}:\n{traceback.format_exc()}')


def run_monthly() -> None:
    log.info('=== Ciclo mensual ===')
    _safe(reps.run, 'reps_scraper')            # all 6 REPS endpoints
    _safe(irca.run, 'irca_scraper')
    _safe(afiliacion.run, 'afiliacion_scraper')
    _safe(supersalud.run, 'supersalud_scraper')
    _safe(ins_pdf.run, 'ins_pdf_scraper')
    _safe(transform.run, 'transform')
    log.info('=== Ciclo mensual completado ===')


def run_annual() -> None:
    log.info('=== Ciclo anual (demografía) ===')
    _safe(demografico.run, 'demografico')
    _safe(transform.run, 'transform')
    log.info('=== Ciclo anual completado ===')


def run_all() -> None:
    log.info('=== Ejecución completa ===')
    _safe(demografico.run, 'demografico')
    _safe(reps.run, 'reps_scraper')
    _safe(irca.run, 'irca_scraper')
    _safe(afiliacion.run, 'afiliacion_scraper')
    _safe(supersalud.run, 'supersalud_scraper')
    _safe(ins_pdf.run, 'ins_pdf_scraper')
    _safe(transform.run, 'transform')
    log.info('=== Ejecución completa finalizada ===')


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
        run_all()
        return
    if args.monthly:
        run_monthly()
        return
    if args.annual:
        run_annual()
        return
    if args.transform_only:
        _safe(transform.run, 'transform')
        return

    # Scheduled mode
    scheduler = BlockingScheduler(timezone='America/Bogota')

    # Monthly: 5th at 08:00
    scheduler.add_job(run_monthly, 'cron', day=5, hour=8, minute=0,
                      id='monthly_refresh', name='Ciclo mensual (IPS + IRCA + Afiliación)')

    # Annual: July 15 at 08:00
    scheduler.add_job(run_annual, 'cron', month=7, day=15, hour=8, minute=0,
                      id='annual_refresh', name='Ciclo anual (Demografía DANE)')

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
