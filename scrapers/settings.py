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
"""

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FILE = ROOT / 'informe_regional.toml'
_CFG = tomllib.loads(_FILE.read_text(encoding='utf-8')) if _FILE.exists() else {}


def _get(env: str, section: str, key: str, default: str) -> str:
    return os.environ.get(env) or _CFG.get(section, {}).get(key) or default


def _path(value: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(value)))
    return p if p.is_absolute() else ROOT / p


DATA_DIR = ROOT / 'data'
MANUAL_DIR = _path(_get('INFORME_MANUAL_DIR', 'rutas', 'manuales', 'data/manual'))
GITHUB_REPO = _get('INFORME_GITHUB_REPO', 'publicacion', 'repo', 'NavinetGroup/dashboard-salud')


def manual_dir(source: str) -> Path:
    """Subfolder of the manual-files folder for one source ('irca', 'afiliacion').
    Created on first use so the operator always knows where to drop files."""
    d = MANUAL_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d
