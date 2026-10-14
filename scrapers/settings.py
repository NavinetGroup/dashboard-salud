# -*- coding: utf-8 -*-
"""
Project settings for the processing machine.

Defaults work out of the box. To change one, copy informe_regional.example.toml
to informe_regional.toml (next to README.md; it is not committed) and edit it,
or set the matching environment variable, which wins over the file.

  [rutas] manuales   INFORME_MANUAL_DIR   folder with the files downloaded by hand
                                          (IRCA CSVs from SIVICAP, afiliación ZIPs).
                                          Today data/manual/; later the SharePoint
                                          library synced with OneDrive, e.g.
                                          "~/Supersalud/Informe Regional - Archivos"
  [publicacion] repo INFORME_GITHUB_REPO  GitHub repo whose releases carry the
                                          monthly database for the viewer app
                                          ('' = do not publish on GitHub)
  [publicacion] carpeta INFORME_PUBLICACION_DIR
                                          shared folder (SharePoint library synced
                                          with OneDrive, network drive) where the
                                          monthly database is copied; every viewer
                                          configured with the same folder picks it up
"""

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FILE = ROOT / 'informe_regional.toml'
_CFG = tomllib.loads(_FILE.read_text(encoding='utf-8')) if _FILE.exists() else {}


def _get(env: str, section: str, key: str, default: str) -> str:
    """Environment variable, else the TOML value, else the default. A variable or
    key set to '' is an explicit value (it switches an optional channel off); only
    an absent one falls through."""
    value = os.environ.get(env)
    if value is None:
        value = _CFG.get(section, {}).get(key)
    return default if value is None else value


def _path(value: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(value)))
    return p if p.is_absolute() else ROOT / p


DATA_DIR = ROOT / 'data'
MANUAL_DIR = _path(_get('INFORME_MANUAL_DIR', 'rutas', 'manuales', 'data/manual') or 'data/manual')
GITHUB_REPO = _get('INFORME_GITHUB_REPO', 'publicacion', 'repo', 'NavinetGroup/dashboard-salud')
_pub = _get('INFORME_PUBLICACION_DIR', 'publicacion', 'carpeta', '')
PUBLISH_DIR = _path(_pub) if _pub else None


def manual_dir(source: str) -> Path:
    """Subfolder of the manual-files folder for one source ('irca', 'afiliacion').
    Created on first use so the operator always knows where to drop files."""
    d = MANUAL_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d
