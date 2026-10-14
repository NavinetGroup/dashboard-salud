# -*- coding: utf-8 -*-
"""Publish the viewer database as a GitHub release (monthly, after the pipeline).

The viewer app reads releases/latest/download/manifest.json on start-up and
downloads the database when the published version is newer than its own copy
(dashboard/data.py). This script uploads both files from data/dist/ (written by
pipeline/exportar.py) to a new release tagged datos-<version> and marks it as
the latest release.

Requires the GitHub CLI (gh) signed in with push rights on the repository set
in informe_regional.toml ([publicacion] repo). Anyone can download a release of
a public repository; no token is needed on the users' side.

    python tools/publicar_datos.py            # asks for confirmation
    python tools/publicar_datos.py --si       # no prompt (scheduled task)
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.settings import GITHUB_REPO  # noqa: E402

DIST = ROOT / 'data' / 'dist'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--si', action='store_true', help='publicar sin pedir confirmación')
    args = ap.parse_args()

    manifest_path = DIST / 'manifest.json'
    if not manifest_path.exists():
        print('No hay nada para publicar: ejecute primero el pipeline (python -m pipeline.runner --monthly).')
        return 2
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    db = DIST / manifest['archivo']
    if not db.exists() or db.stat().st_size != manifest['bytes']:
        print(f'{db.name} no coincide con manifest.json: vuelva a exportar (python -m pipeline.exportar).')
        return 2
    if not shutil.which('gh'):
        print('Falta la herramienta "gh" (GitHub CLI): https://cli.github.com — luego "gh auth login".')
        return 2

    tag = f"datos-{manifest['version']}"
    print(f'Repositorio: {GITHUB_REPO}\nVersión:     {manifest["version"]}\n'
          f'Archivo:     {db.name} ({manifest["bytes"] / 1e6:.1f} MB)\nRelease:     {tag} (pública)')
    if not args.si and input('¿Publicar? [s/N] ').strip().lower() not in ('s', 'si', 'sí'):
        print('Cancelado.')
        return 1
    notes = (f"Base de datos del visor, versión {manifest['version']} "
             f"(generada {manifest['generado']}). SHA-256 {manifest['sha256']}.")
    cmd = ['gh', 'release', 'create', tag, str(db), str(manifest_path), '--repo', GITHUB_REPO,
           '--title', f"Datos {manifest['version']}", '--notes', notes, '--latest']
    r = subprocess.run(cmd)
    if r.returncode == 0:
        print(f'Publicado. Las aplicaciones se actualizarán al abrirse: '
              f'https://github.com/{GITHUB_REPO}/releases/tag/{tag}')
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
