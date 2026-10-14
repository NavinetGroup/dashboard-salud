# -*- coding: utf-8 -*-
"""Build the portable Windows viewer: a folder (and zip) anyone can open.

    python tools/build_portable.py

Output: dist/InformeRegional/ and dist/InformeRegional_<version>.zip

    InformeRegional/
      Abrir Informe Regional.bat   double-click: starts the app on a free port, opens the browser
      LEEME.txt
      python/                      Python 3.12 embeddable (python.org) + the 6 viewer packages
      app/
        .streamlit/config.toml
        dashboard/                 the app
        data/
          informe_regional_visor.duckdb   current data (works offline from day one)
          actualizacion/           drop a newer database here (manual update)

Nothing is installed on the user's machine and no administrator rights are
needed. Updates arrive by themselves (GitHub release, see dashboard/data.py);
code updates mean handing out a new zip. Run on Windows x64 with the project's
Python 3.12 venv (pip installs the packages for the embedded interpreter).
"""

import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
OUT = DIST / 'InformeRegional'
PY_VERSION = '3.12.10'      # must match the venv's minor version (wheels are cp312)
PY_URL = f'https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip'
PORT = 8765

LAUNCHER = r'''@echo off
title Informe Regional de Salud
cd /d "%~dp0app"
echo.
echo   Informe Regional de Salud
echo   ------------------------------------------------------------
echo   Abriendo el tablero en el navegador...
echo   Mantenga esta ventana abierta mientras usa el tablero;
echo   cierrela para salir.
echo.
"%~dp0python\python.exe" abrir.py
if errorlevel 1 pause
'''

# Starts Streamlit on the first free local port (another program may already
# use the default one) and lets Streamlit open the browser on it.
OPENER = f'''import socket
import sys


def _free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) != 0   # nothing answering there


port = next((p for p in range({PORT}, {PORT} + 40) if _free(p)), None)
if port is None:
    sys.exit('No hay un puerto local libre entre {PORT} y {PORT + 39}.')
sys.argv = ['streamlit', 'run', 'dashboard/app.py', '--server.port', str(port),
            '--server.address', 'localhost', '--server.headless', 'false',
            '--browser.gatherUsageStats', 'false', '--global.developmentMode', 'false']
from streamlit.web import cli
sys.exit(cli.main())
'''

README = f'''INFORME REGIONAL DE SALUD — Supersalud
=====================================

ABRIR
  Doble clic en "Abrir Informe Regional.bat". Se abre el navegador con el
  tablero. Mantenga abierta la ventana negra mientras
  lo usa; ciérrela para salir. No requiere instalación ni permisos de administrador.

DATOS
  - Actualización automática: al abrir, si hay internet, el tablero descarga
    la versión mensual más reciente publicada. La versión aparece en la barra
    lateral ("Datos: versión ...").
  - Sin internet: siga usando la versión que tiene. Para actualizar a mano,
    copie el archivo informe_regional_visor.duckdb que le compartan en
    app\\data\\actualizacion\\ y vuelva a abrir el tablero.

PROBLEMAS
  - Si el navegador no se abre, copie en él la dirección que muestra la ventana negra
    (http://localhost:...).
'''


def _download(url: str) -> bytes:
    print(f'  descargando {url}')
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def _trim(site: Path) -> int:
    """Delete what the viewer never loads: test suites bundled in the wheels,
    C/C++ headers and link libraries, Cython sources, bytecode caches and
    Plotly's Jupyter extensions. Returns the bytes removed."""
    size = lambda p: sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.is_dir() else p.stat().st_size
    targets = [d for d in site.rglob('*') if d.is_dir() and d.name in ('tests', 'test', '__pycache__')]
    targets += [site / 'share', site / 'pyarrow' / 'include', site / 'pyarrow' / 'src',
                site / 'numpy' / '_core' / 'include']
    targets += [f for pat in ('*.pxd', '*.pyx', '*.lib', '*.h', '*.hpp', '*.cpp', '*.pyi')
                for f in site.rglob(pat)]
    removed = 0
    for x in targets:
        if not x.exists():
            continue
        removed += size(x)
        shutil.rmtree(x) if x.is_dir() else x.unlink()
    return removed


def main() -> int:
    manifest = ROOT / 'data' / 'dist' / 'manifest.json'
    if not manifest.exists():
        print('Falta data/dist/: ejecute el pipeline o "python -m pipeline.exportar" primero.')
        return 2
    version = json.loads(manifest.read_text(encoding='utf-8'))['version']
    if OUT.exists():
        shutil.rmtree(OUT)
    py_dir, app_dir = OUT / 'python', OUT / 'app'

    print('1/4 Python embebido')
    zipfile.ZipFile(io.BytesIO(_download(PY_URL))).extractall(py_dir)
    pth = next(py_dir.glob('python3*._pth'))
    # site-packages on the path and `import site` on, so -m streamlit works
    pth.write_text(pth.read_text().replace('#import site', 'import site')
                   + 'Lib\\site-packages\n', encoding='ascii')

    print('2/4 Paquetes del visor (requirements.txt)')
    # requirements.txt pins only the 6 direct packages; their dependencies are
    # constrained to the exact versions in the venv the app is tested with (a
    # newer Starlette/Uvicorn than Streamlit expects serves blank pages).
    frozen = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], check=True,
                            capture_output=True, text=True).stdout
    constraints = DIST / 'constraints.txt'
    constraints.write_text(frozen, encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--no-warn-script-location',
                    '--only-binary=:all:', '--target', str(py_dir / 'Lib' / 'site-packages'),
                    '-r', str(ROOT / 'requirements.txt'), '-c', str(constraints)], check=True)

    removed = _trim(py_dir / 'Lib' / 'site-packages')
    print(f'  recortados {removed / 1e6:.0f} MB que el visor no usa (tests, cabeceras C, extensiones Jupyter)')

    print('3/4 Aplicación y datos')
    shutil.copytree(ROOT / 'dashboard', app_dir / 'dashboard',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / '.streamlit', app_dir / '.streamlit')
    (app_dir / 'data' / 'actualizacion').mkdir(parents=True)
    shutil.copy2(ROOT / 'data' / 'dist' / 'informe_regional_visor.duckdb', app_dir / 'data')
    (OUT / 'Abrir Informe Regional.bat').write_text(LAUNCHER.replace('\n', '\r\n'), encoding='cp1252')
    (app_dir / 'abrir.py').write_text(OPENER, encoding='utf-8')
    (OUT / 'LEEME.txt').write_text(README.replace('\n', '\r\n'), encoding='utf-8-sig')

    print('4/4 Comprimiendo')
    zip_path = DIST / f'InformeRegional_{version}.zip'
    zip_path.unlink(missing_ok=True)
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', DIST, OUT.name)
    size = sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    print(f'Listo: {OUT} ({size / 1e6:.0f} MB) y {zip_path.name} ({zip_path.stat().st_size / 1e6:.0f} MB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
