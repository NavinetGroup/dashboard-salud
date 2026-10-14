# -*- coding: utf-8 -*-
"""Assemble the hand-over package for the organisation that will host and
support the system (source code, manuals, portable viewer, historical data).

    python tools/build_entrega.py              # everything
    python tools/build_entrega.py --sin-datos  # without data/parquet

Output: dist/Entrega_<fecha>/
    codigo_fuente_<fecha>_<commit>.zip   the repository at HEAD (git archive: no
                                         data, no local configuration, no mockup)
    InformeRegional_<versión>.zip        portable viewer (tools/build_portable.py)
    MANUAL_USUARIO.docx / .md            user manual
    MANUAL_TECNICO.docx / .md            technical manual
    datos_historicos_parquet_<fecha>.zip data/parquet: the downloaded sources,
                                         including the monthly photos that the
                                         sources no longer serve (BDUA, REPS,
                                         Supersalud); the database is rebuilt
                                         from them with --transform-only
    LEEME_ENTREGA.txt                    contents and first steps

Run after tools/build_docs.py and tools/build_portable.py.
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
DOCS = ROOT / 'docs'

LEEME = '''INFORME REGIONAL DE SALUD — PAQUETE DE ENTREGA ({fecha})
======================================================

Contenido
  codigo_fuente_*.zip            Código fuente completo (commit {commit}). Sin datos ni
                                 configuración local. Ver "Manual técnico", sección
                                 "Paquete de entrega e instalación desde el código fuente".
  InformeRegional_*.zip          Tablero portable para los usuarios: se descomprime y se
                                 abre con "Abrir Informe Regional.bat". Para publicarlo en
                                 SharePoint ver "Manual técnico", sección "Distribución".
  MANUAL_USUARIO.docx / .md      Manual del usuario del tablero.
  MANUAL_TECNICO.docx / .md      Manual técnico: arquitectura, fuentes, operación mensual,
                                 extensión y solución de problemas.
  datos_historicos_parquet_*.zip Fuentes ya descargadas (data/parquet). Conservarlas: las
                                 fotos mensuales de BDUA, REPS y Supersalud no se pueden
                                 volver a descargar.

Primeros pasos para el equipo de soporte
  1. Descomprimir codigo_fuente_*.zip en una carpeta de trabajo.
  2. Descomprimir datos_historicos_parquet_*.zip dentro de esa carpeta, en data\\parquet\\.
  3. Instalar Python 3.12 y Google Chrome; doble clic en "Preparar equipo.bat".
  4. Copiar informe_regional.example.toml como informe_regional.toml y fijar el canal de
     publicación ([publicacion] carpeta o repo).
  5. .venv\\Scripts\\python.exe -m pipeline.runner --transform-only   (reconstruye la base)
  6. .venv\\Scripts\\python.exe -m streamlit run dashboard\\app.py      (verifica el tablero)
  Cada mes: "Actualizar datos.bat" (Manual técnico, sección "Operación").
'''


def _git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sin-datos', action='store_true', help='no incluir data/parquet')
    args = ap.parse_args()

    today = f'{date.today():%Y-%m-%d}'
    commit = _git('rev-parse', '--short', 'HEAD')
    if _git('status', '--porcelain', '--untracked-files=no'):
        print('Hay cambios sin confirmar en git: confírmelos primero para que el zip de código los incluya.')
        return 2
    portable = sorted(DIST.glob('InformeRegional_*.zip'), key=lambda p: p.stat().st_mtime)
    missing = [str(p) for p in (DOCS / 'MANUAL_USUARIO.docx', DOCS / 'MANUAL_TECNICO.docx') if not p.exists()]
    if not portable:
        missing.append('dist/InformeRegional_<versión>.zip (tools/build_portable.py)')
    if missing:
        print('Falta: ' + ', '.join(missing))
        return 2

    out = DIST / f'Entrega_{today}'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print('1/4 Código fuente')
    code_zip = out / f'codigo_fuente_{today}_{commit}.zip'
    subprocess.run(['git', 'archive', '--format=zip', f'--prefix=InformeRegional-codigo/', '-o', str(code_zip), 'HEAD'],
                   cwd=ROOT, check=True)

    print('2/4 Manuales y tablero portable')
    for name in ('MANUAL_USUARIO.docx', 'MANUAL_USUARIO.md', 'MANUAL_TECNICO.docx', 'MANUAL_TECNICO.md'):
        shutil.copy2(DOCS / name, out / name)
    shutil.copy2(portable[-1], out / portable[-1].name)

    if not args.sin_datos:
        print('3/4 Datos históricos (data/parquet)')
        parquet = ROOT / 'data' / 'parquet'
        with zipfile.ZipFile(out / f'datos_historicos_parquet_{today}.zip', 'w', zipfile.ZIP_STORED) as z:
            for f in sorted(parquet.rglob('*')):
                if f.is_file():
                    z.write(f, f'parquet/{f.relative_to(parquet).as_posix()}')
    else:
        print('3/4 Datos históricos: omitidos (--sin-datos)')

    print('4/4 LEEME')
    (out / 'LEEME_ENTREGA.txt').write_text(LEEME.format(fecha=today, commit=commit).replace('\n', '\r\n'),
                                            encoding='utf-8-sig')
    size = sum(f.stat().st_size for f in out.iterdir())
    print(f'Listo: {out} ({size / 1e6:.0f} MB)')
    for f in sorted(out.iterdir()):
        print(f'  {f.name:45s} {f.stat().st_size / 1e6:7.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
