# -*- coding: utf-8 -*-
"""
Export the slim database for the viewer app.

The pipeline's database holds every raw source table (REPS services, SIVIGILA
cases, CUIPO rows, …). The dashboard only reads the metric tables the pipeline
derives from them, so the copy distributed to users carries just those:

  metricas_{municipio,departamento,nacional}_{periodo,anterior}
  piramide_afiliados
  _visor_info            version, build time, latest period per source

Output (data/dist/):
  informe_regional_visor.duckdb
  manifest.json          {"version", "archivo", "sha256", "bytes", "generado"}

The viewer compares manifest.version with its own copy to decide whether to
download a new one (dashboard/data.py); tools/publicar_datos.py uploads both
files to the GitHub release.
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
LIVE_DB = BASE_DIR / 'data' / 'informe_regional.duckdb'
DIST_DIR = BASE_DIR / 'data' / 'dist'
VIEWER_DB = 'informe_regional_visor.duckdb'

TABLES = [f'metricas_{lvl}_{kind}' for lvl in ('municipio', 'departamento', 'nacional')
          for kind in ('periodo', 'anterior')] + ['piramide_afiliados']

# Latest period of each source, shown in the app's "acerca de los datos"
_PERIODS = {
    'sivigila':     "SELECT MAX(anio * 100 + semana) FROM sivigila_casos",
    'cuipo':        "SELECT MAX(anio * 100 + mes) FROM cuipo_salud",
    'cofinanciacion': "SELECT MAX(anio * 100 + mes) FROM cofin_lma",
    'ins_vsp':      "SELECT MAX(anio * 10 + trimestre) FROM ins_vsp",
}


def run(base_dir: str | None = None, db_path: 'str | Path | None' = None) -> Path:
    base = Path(base_dir) if base_dir else BASE_DIR
    src = Path(db_path) if db_path else base / 'data' / 'informe_regional.duckdb'
    dist = base / 'data' / 'dist'
    dist.mkdir(parents=True, exist_ok=True)
    out = dist / VIEWER_DB
    part = dist / f'{VIEWER_DB}.part'
    part.unlink(missing_ok=True)

    now = datetime.now()
    version = now.strftime('%Y.%m.%d-%H%M')
    con = duckdb.connect(str(part))
    try:
        con.execute(f"ATTACH '{src.as_posix()}' AS src (READ_ONLY)")
        have = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'src'").fetchall()}
        missing = [t for t in TABLES if t not in have]
        if missing:
            raise RuntimeError(f'exportar: faltan tablas en {src.name}: {missing}. Ejecute el pipeline.')
        for t in TABLES:
            con.execute(f'CREATE TABLE {t} AS SELECT * FROM src.{t}')
        info = {'version': version, 'generado': now.isoformat(timespec='seconds')}
        for name, sql in _PERIODS.items():
            try:
                info[f'ultimo_{name}'] = str(con.execute(
                    sql.replace('FROM ', 'FROM src.')).fetchone()[0])
            except duckdb.Error:
                pass
        con.execute('CREATE TABLE _visor_info (clave VARCHAR, valor VARCHAR)')
        con.executemany('INSERT INTO _visor_info VALUES (?, ?)', list(info.items()))
        con.execute('DETACH src')
        con.execute('CHECKPOINT')
    finally:
        con.close()
    part.replace(out)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest = {'version': version, 'archivo': VIEWER_DB, 'sha256': digest,
                'bytes': out.stat().st_size, 'generado': now.isoformat(timespec='seconds')}
    (dist / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                         encoding='utf-8')
    print(f'exportar OK — {out.name}: {out.stat().st_size / 1e6:.1f} MB, versión {version}')
    return out


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    run()
