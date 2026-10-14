# -*- coding: utf-8 -*-
"""Publish the viewer database (monthly, after the pipeline).

Two channels, both set in informe_regional.toml ([publicacion]); either or both:

  carpeta   a shared folder (a SharePoint library synced with OneDrive, a network
            drive): the database and manifest.json are copied there. Every viewer
            whose [tablero] carpeta_actualizacion points to the same folder installs
            the new version when it opens. Works without GitHub or internet access
            beyond the organisation.
  repo      a GitHub repository: a public release tagged datos-<version> with both
            files, marked as latest. Viewers read releases/latest/download/manifest.json.
            Needs the GitHub CLI (gh) signed in with push rights.

Both files come from data/dist/ (written by pipeline/exportar.py).

    python tools/publicar_datos.py            # asks for confirmation
    python tools/publicar_datos.py --si       # no prompt (scheduled task)
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.settings import GITHUB_REPO, PUBLISH_DIR  # noqa: E402

DIST = ROOT / 'data' / 'dist'


def _to_folder(db: Path, manifest_path: Path, folder: Path) -> None:
    """Copy both files; the database first and atomically, the manifest last, so a
    viewer that reads the folder mid-copy never sees a manifest for a missing file."""
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (db.name + '.part')
    shutil.copyfile(db, part)
    os.replace(part, folder / db.name)
    shutil.copyfile(manifest_path, folder / manifest_path.name)


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
    if not db.exists() or hashlib.sha256(db.read_bytes()).hexdigest() != manifest['sha256']:
        print(f'{db.name} no coincide con manifest.json: vuelva a exportar (python -m pipeline.exportar).')
        return 2
    if PUBLISH_DIR is None and not GITHUB_REPO:
        print('No hay canal de publicación: fije [publicacion] carpeta o repo en informe_regional.toml.')
        return 2

    print(f"Versión:  {manifest['version']}\nArchivo:  {db.name} ({manifest['bytes'] / 1e6:.1f} MB)")
    if PUBLISH_DIR is not None:
        print(f'Carpeta:  {PUBLISH_DIR}')
    if GITHUB_REPO:
        print(f'GitHub:   {GITHUB_REPO}, release pública datos-{manifest["version"]}')
    if not args.si and input('¿Publicar? [s/N] ').strip().lower() not in ('s', 'si', 'sí'):
        print('Cancelado.')
        return 1

    rc = 0
    if PUBLISH_DIR is not None:
        try:
            _to_folder(db, manifest_path, PUBLISH_DIR)
            print(f'Copiado a {PUBLISH_DIR}. Los tableros que usan esa carpeta se actualizarán al abrirse.')
        except OSError as e:
            print(f'No se pudo copiar a la carpeta compartida: {e}')
            rc = 1
    if GITHUB_REPO:
        if not shutil.which('gh'):
            print('Falta la herramienta "gh" (GitHub CLI): https://cli.github.com — luego "gh auth login".')
            return 2
        tag = f"datos-{manifest['version']}"
        notes = (f"Base de datos del visor, versión {manifest['version']} "
                 f"(generada {manifest['generado']}). SHA-256 {manifest['sha256']}.")
        r = subprocess.run(['gh', 'release', 'create', tag, str(db), str(manifest_path), '--repo', GITHUB_REPO,
                            '--title', f"Datos {manifest['version']}", '--notes', notes, '--latest'])
        if r.returncode == 0:
            print(f'Publicado: https://github.com/{GITHUB_REPO}/releases/tag/{tag}')
        rc = rc or r.returncode
    return rc


if __name__ == '__main__':
    sys.exit(main())
