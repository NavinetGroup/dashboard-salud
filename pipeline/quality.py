# -*- coding: utf-8 -*-
"""
quality.py — Controles de calidad de datos tras cada transform.

Cada control devuelve ok / no-ok con un nivel:
  error  → el dato publicado sería incorrecto (p. ej. llaves duplicadas, meses
           re-etiquetados, municipios sin código). Hace fallar el paso 'calidad'
           del runner, y la notificación mensual llega como CON FALLOS.
  warn   → algo inusual que conviene revisar (fuente atrasada, salto de filas).

Los resultados se guardan en _calidad_resultados (histórico) y los conteos de
filas en _carga_log, que el siguiente run usa para detectar saltos.

Los umbrales salen de la línea base del 2026-10-13, con los errores corregidos
en la auditoría como casos que deben fallar (ver docs/AUDITORIA_2026-10-13.md).

Run: python pipeline/quality.py
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / 'data' / 'informe_regional.duckdb'

_MES_CASE = """CASE UPPER(TRIM(mes))
    WHEN 'ENERO' THEN 1 WHEN 'FEBRERO' THEN 2 WHEN 'MARZO' THEN 3 WHEN 'ABRIL' THEN 4
    WHEN 'MAYO' THEN 5 WHEN 'JUNIO' THEN 6 WHEN 'JULIO' THEN 7 WHEN 'AGOSTO' THEN 8
    WHEN 'SEPTIEMBRE' THEN 9 WHEN 'OCTUBRE' THEN 10 WHEN 'NOVIEMBRE' THEN 11
    WHEN 'DICIEMBRE' THEN 12 ELSE 0 END"""

# Afiliación rows that legitimately have no municipality
_AFIL_SIN_MUN = "(municipio IS NULL OR municipio LIKE '%-SM' OR municipio ILIKE 'SIN UBICACI%')"

# Tables whose row count is compared with the previous load
_TRACKED = [
    'reps_prestadores', 'reps_sedes', 'reps_servicios', 'reps_capacidad',
    'reps_medidas_seguridad', 'reps_sanciones',
    'supersalud_ips_intervenidas', 'supersalud_eps_intervenidas',
    'afiliacion', 'irca', 'demografico_edad_sexo', 'demografico_etnico',
]


class QualityError(RuntimeError):
    """One or more error-level quality checks failed."""


@dataclass
class Result:
    check: str
    level: str          # 'error' | 'warn'
    ok: bool
    detail: str


class _Checks:
    def __init__(self, con: duckdb.DuckDBPyConnection, today: date):
        self.con = con
        self.today = today
        self.results: list[Result] = []
        self.objects = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}

    # -- helpers --------------------------------------------------------------
    def one(self, sql: str):
        return self.con.execute(sql).fetchone()

    def add(self, check: str, level: str, ok: bool, detail: str) -> None:
        self.results.append(Result(check, level, bool(ok), detail))

    def has(self, *names: str) -> bool:
        return all(n in self.objects for n in names)

    # -- 1. structure ---------------------------------------------------------
    def structure(self) -> None:
        n_mun, n_mun_u = self.one("SELECT COUNT(*), COUNT(DISTINCT geo_mun_codigo) FROM v_metricas_municipio")
        self.add('metricas_municipio_filas', 'error', n_mun == n_mun_u == 1123,
                 f'{n_mun} filas, {n_mun_u} códigos distintos (esperado 1123)')
        n_dep, n_dep_u = self.one("SELECT COUNT(*), COUNT(DISTINCT geo_dep_codigo) FROM v_metricas_departamento")
        self.add('metricas_departamento_filas', 'error', n_dep == n_dep_u == 33,
                 f'{n_dep} filas, {n_dep_u} códigos distintos (esperado 33)')
        for level, key in (('municipio', 'geo_mun_codigo'), ('departamento', 'geo_dep_codigo')):
            t = f'metricas_{level}_periodo'
            if self.has(t):
                dups = self.one(f"""SELECT COUNT(*) FROM (
                    SELECT anio_filtro, mes_filtro, {key} FROM {t}
                    GROUP BY ALL HAVING COUNT(*) > 1)""")[0]
                self.add(f'{t}_llave_unica', 'error', dups == 0, f'{dups} llaves (periodo, entidad) repetidas')

    # -- 2. duplicated natural keys in source tables --------------------------
    def duplicates(self) -> None:
        keys = {
            'irca': 'anio, mes, codigo_mun',
            'afiliacion': 'anio, mes, departamento, municipio',
            'reps_prestadores': 'codigo_habilitacion',
            'supersalud_ips_intervenidas': 'nit, entidad',
            'supersalud_eps_intervenidas': 'nit, entidad',
        }
        for t, k in keys.items():
            if not self.has(t):
                continue
            dups = self.one(f"SELECT COUNT(*) FROM (SELECT {k} FROM {t} GROUP BY ALL HAVING COUNT(*) > 1)")[0]
            self.add(f'{t}_sin_duplicados', 'error', dups == 0, f'{dups} llaves ({k}) repetidas')
        # A REPS record split by a line break inside a field becomes half-rows with
        # shifted columns, and footer lines ('Fecha corte REPS: ...') can be read as
        # data: both show up as an invalid habilitation code. Valid codes are the
        # 5-digit DIVIPOLA prefix + 5 characters (MinSalud has typed 'O' for '0').
        for t in ('reps_prestadores', 'reps_sedes', 'reps_servicios', 'reps_capacidad',
                  'reps_medidas_seguridad', 'reps_sanciones'):
            if not self.has(t):
                continue
            n = self.one(f"""SELECT COUNT(*) FROM {t} WHERE NOT regexp_matches(
                             COALESCE(codigo_habilitacion, ''), '^[0-9]{{4,5}}[0-9A-Z]{{5}}$')""")[0]
            self.add(f'{t}_filas_completas', 'error', n == 0,
                     f'{n} filas con código de habilitación inválido (¿filas partidas o pie de página?)')

    # -- 3. geographic matching ----------------------------------------------
    def geo_match(self) -> None:
        # (view, rows considered, minimum % with municipality code, level)
        mun_sources = [
            ('v_afiliacion', f'NOT {_AFIL_SIN_MUN}', 99.5, 'error'),
            ('v_reps_prestadores', 'TRUE', 99.5, 'error'),
            ('v_reps_sedes', 'TRUE', 99.5, 'error'),
            ('v_reps_servicios', 'TRUE', 99.5, 'error'),
            ('v_reps_capacidad', 'TRUE', 99.5, 'error'),
            ('v_irca', 'TRUE', 99.5, 'error'),
            # INS PDF tables carry footnotes / header residue as rows
            ('v_ins_desnutricion_aguda', 'municipio IS NOT NULL', 90, 'warn'),
            ('v_ins_intento_suicidio', 'municipio IS NOT NULL', 90, 'warn'),
            ('v_ins_mortalidad_materna', 'municipio IS NOT NULL', 75, 'warn'),
        ]
        for view, where, minimum, level in mun_sources:
            if not self.has(view):
                continue
            pct, n = self.one(f"""SELECT 100.0 * COUNT(geo_mun_codigo) / NULLIF(COUNT(*), 0), COUNT(*)
                                  FROM {view} WHERE {where}""")
            pct = pct or 0.0
            self.add(f'{view}_match_municipio', level, pct >= minimum,
                     f'{pct:.2f}% de {n:,} filas con código de municipio (mínimo {minimum}%)')
        dep_sources = ['v_ins_dengue', 'v_ins_violencia_genero', 'v_ins_mortalidad_menores5',
                       'v_ins_sifilis_congenita', 'v_supersalud_ips_intervenidas',
                       'v_supersalud_eps_intervenidas', 'v_dift18_departamento']
        for view in dep_sources:
            if not self.has(view):
                continue
            pct, n = self.one(f"""SELECT 100.0 * COUNT(geo_dep_codigo) / NULLIF(COUNT(*), 0), COUNT(*)
                                  FROM {view}""")
            pct = pct or 0.0
            self.add(f'{view}_match_departamento', 'warn', pct >= 90,
                     f'{pct:.1f}% de {n:,} filas con código de departamento (mínimo 90%)')

    # -- 4. consistency between sources ---------------------------------------
    def consistency(self) -> None:
        pob, etn = self.one("SELECT SUM(pob_total), SUM(pob_etnico_total) FROM v_metricas_departamento")
        if pob and etn:
            ratio = etn / pob
            # Both are DANE projections of the same year; they differ per department
            # (separate series) but agree nationally within ~0.2 %.
            self.add('poblacion_etnica_vs_total', 'error', 0.98 <= ratio <= 1.02,
                     f'étnica / total nacional = {ratio:.4f} (esperado 0,98–1,02)')
        n_pob = self.one("SELECT COUNT(pob_total) FROM v_metricas_municipio")[0]
        self.add('poblacion_todos_municipios', 'error', n_pob == 1123,
                 f'{n_pob} de 1123 municipios con población')
        if self.has('v_afiliacion'):
            n_afil = self.one("SELECT COUNT(afiliados_total) FROM v_metricas_municipio")[0]
            self.add('afiliacion_cobertura_municipios', 'warn', n_afil >= 1100,
                     f'{n_afil} de 1123 municipios con afiliación (mínimo 1100)')
            # The 'MAYO 2026 = copy of MARZO' bug: two months with identical totals
            same = self.con.execute(f"""
                SELECT LIST(anio || '-' || mes ORDER BY anio, {_MES_CASE}) FROM (
                    SELECT anio, mes, SUM(afiliados_total) AS t FROM v_afiliacion
                    WHERE geo_mun_codigo IS NOT NULL GROUP BY 1, 2)
                GROUP BY t HAVING COUNT(*) > 1""").fetchall()
            self.add('afiliacion_meses_distintos', 'error', not same,
                     'meses con total idéntico (¿un mes re-etiquetado?): '
                     + '; '.join(', '.join(r[0]) for r in same) if same else 'todos los meses difieren')
            jumps = self.con.execute(f"""
                SELECT anio, mes, t, prev FROM (
                    SELECT anio, mes, t,
                           LAG(t) OVER (ORDER BY anio, {_MES_CASE}) AS prev FROM (
                        SELECT anio, mes, SUM(afiliados_total) AS t FROM v_afiliacion
                        WHERE geo_mun_codigo IS NOT NULL GROUP BY 1, 2))
                WHERE prev IS NOT NULL AND ABS(t - prev) > 0.03 * prev""").fetchall()
            self.add('afiliacion_variacion_mensual', 'warn', not jumps,
                     'variación > 3 %: ' + '; '.join(f'{a}-{m}: {p:,.0f} → {t:,.0f}' for a, m, t, p in jumps)
                     if jumps else 'variación mensual del total ≤ 3 %')

    # -- 5. plausible ranges ---------------------------------------------------
    def ranges(self) -> None:
        bounds = [
            ('cobertura_pct', 0, 100),
            ('irca_promedio', 0, 100),
            ('prevalencia_desnutricion_aguda', 0, 20),      # percent
            ('incidencia_dengue_x100k', 0, 5000),
            ('razon_mortalidad_materna', 0, 2000),          # department level
            ('tasa_intento_suicidio', 0, 1000),
            ('violencia_fisica', 0, 2000),
            ('tasa_mortalidad_menores5_dnt', 0, 500),
        ]
        cols = {r[0] for r in self.con.execute("DESCRIBE v_metricas_departamento").fetchall()}
        for col, lo, hi in bounds:
            if col not in cols:
                continue
            bad = self.con.execute(f"""SELECT departamento, {col} FROM v_metricas_departamento
                                       WHERE {col} < {lo} OR {col} > {hi}""").fetchall()
            self.add(f'rango_{col}', 'error', not bad,
                     f'fuera de [{lo}, {hi}]: ' + ', '.join(f'{d}={v:,.1f}' for d, v in bad[:5])
                     if bad else f'todos los departamentos en [{lo}, {hi}]')
        if self.has('v_metricas_nacional'):
            cob = self.one("SELECT cobertura_pct FROM v_metricas_nacional")[0]
            if cob is not None:
                self.add('cobertura_nacional', 'warn', 85 <= cob <= 100,
                         f'cobertura nacional {cob:.1f} % (esperado 85–100 %)')

    # -- 6. freshness ----------------------------------------------------------
    def freshness(self) -> None:
        def months_since(y: int, m: int) -> int:
            return (self.today.year - y) * 12 + self.today.month - m

        if self.has('afiliacion'):
            y, m = self.one(f"SELECT anio, {_MES_CASE} FROM afiliacion ORDER BY anio DESC, {_MES_CASE} DESC LIMIT 1")
            age = months_since(y, m)
            self.add('frescura_afiliacion', 'warn', age <= 3, f'último mes {y}-{m:02d} ({age} meses)')
        if self.has('irca'):
            y, m = self.one(f"SELECT anio, {_MES_CASE} FROM irca ORDER BY anio DESC, {_MES_CASE} DESC LIMIT 1")
            age = months_since(y, m)
            self.add('frescura_irca', 'warn', age <= 4,
                     f'último mes {y}-{m:02d} ({age} meses) — requiere descarga manual de SIVICAP')
        if self.has('reps_prestadores'):
            snap = self.one("SELECT MAX(snapshot) FROM reps_prestadores")[0]
            if snap:
                y, m = int(snap[:4]), int(snap[5:7])
                age = months_since(y, m)
                self.add('frescura_reps', 'warn', age <= 2, f'snapshot {snap} ({age} meses)')
        # INS periods are ~4 weeks; PE n ends around week 4n of the year
        for t in ('ins_dengue', 'ins_mortalidad_materna', 'ins_desnutricion_aguda',
                  'ins_intento_suicidio', 'ins_violencia_genero'):
            if not self.has(t):
                continue
            row = self.one(f"""SELECT anio, periodo_epidemiologico FROM {t}
                ORDER BY anio DESC, CASE periodo_epidemiologico
                    WHEN 'I' THEN 1 WHEN 'II' THEN 2 WHEN 'III' THEN 3 WHEN 'IV' THEN 4
                    WHEN 'V' THEN 5 WHEN 'VI' THEN 6 WHEN 'VII' THEN 7 WHEN 'VIII' THEN 8
                    WHEN 'IX' THEN 9 WHEN 'X' THEN 10 WHEN 'XI' THEN 11 WHEN 'XII' THEN 12
                    WHEN 'XIII' THEN 13 ELSE 0 END DESC LIMIT 1""")
            if not row:
                continue
            y, pe = row
            roman = ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII')
            n = roman.index(pe) + 1 if pe in roman else 0
            current_pe = (self.today.year, min(13, (self.today.timetuple().tm_yday - 1) // 28 + 1))
            lag = (current_pe[0] - y) * 13 + current_pe[1] - n
            self.add(f'frescura_{t}', 'warn', lag <= 3,
                     f'último periodo {y} PE {pe} ({lag} periodos de atraso)')

    # -- 7. row-count jumps vs previous load ----------------------------------
    def row_jumps(self) -> None:
        self.con.execute("""CREATE TABLE IF NOT EXISTS _carga_log (
            cargado_en TIMESTAMP, tabla VARCHAR, filas BIGINT)""")
        prev = dict(self.con.execute("""
            SELECT tabla, filas FROM _carga_log
            QUALIFY ROW_NUMBER() OVER (PARTITION BY tabla ORDER BY cargado_en DESC) = 1""").fetchall())
        now = datetime.now()
        for t in _TRACKED:
            if not self.has(t):
                continue
            n = self.one(f"SELECT COUNT(*) FROM {t}")[0]
            p = prev.get(t)
            if p:
                change = (n - p) / p
                # Snapshot registers (REPS, Supersalud) and cumulative tables should
                # move slowly; a halving or doubling means a broken load.
                level = 'error' if change < -0.5 or change > 1.0 else 'warn'
                self.add(f'filas_{t}', level, abs(change) <= 0.3,
                         f'{p:,} → {n:,} filas ({change:+.0%} vs. carga anterior)')
            self.con.execute("INSERT INTO _carga_log VALUES (?, ?, ?)", [now, t, n])

    def run_all(self) -> list[Result]:
        for step in (self.structure, self.duplicates, self.geo_match, self.consistency,
                     self.ranges, self.freshness, self.row_jumps):
            try:
                step()
            except Exception as e:   # a broken check must be visible, not skipped
                self.add(step.__name__, 'error', False, f'el control falló: {e}')
        return self.results


def check(db_path: 'str | Path', today: date | None = None) -> list[Result]:
    """Run every check against db_path, store results, and return them."""
    con = duckdb.connect(str(db_path))
    try:
        results = _Checks(con, today or date.today()).run_all()
        con.execute("""CREATE TABLE IF NOT EXISTS _calidad_resultados (
            ejecutado_en TIMESTAMP, control VARCHAR, nivel VARCHAR, ok BOOLEAN, detalle VARCHAR)""")
        ts = datetime.now()
        con.executemany("INSERT INTO _calidad_resultados VALUES (?, ?, ?, ?, ?)",
                        [(ts, r.check, r.level, r.ok, r.detail) for r in results])
        return results
    finally:
        con.close()


def run(base_dir: str | None = None, db_path: 'str | Path | None' = None) -> None:
    """Runner entry point: print the report; raise QualityError on any failed error-level check."""
    db = (Path(db_path) if db_path else
          Path(base_dir) / 'data' / 'informe_regional.duckdb' if base_dir else DB_PATH)
    results = check(db)
    failed_errors = [r for r in results if not r.ok and r.level == 'error']
    failed_warns = [r for r in results if not r.ok and r.level == 'warn']

    print(f'calidad: {len(results)} controles — {len(failed_errors)} errores, '
          f'{len(failed_warns)} advertencias')
    for r in failed_errors + failed_warns:
        print(f'  [{r.level.upper():5}] {r.check}: {r.detail}')
    if failed_errors:
        raise QualityError(f'{len(failed_errors)} control(es) de calidad fallaron: '
                           + ', '.join(r.check for r in failed_errors))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
