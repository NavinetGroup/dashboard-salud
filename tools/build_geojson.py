# -*- coding: utf-8 -*-
"""Build the dashboard's map files from DANE's Marco Geoestadístico Nacional.

Source: DANE geoportal, MGN 2025 FeatureServer (public ArcGIS REST, no login):
  layer 319 Departamento · layer 317 Municipio
Geometry is simplified on the server (maxAllowableOffset, degrees) and rounded
to 4 decimals (~11 m) so the files stay small enough to ship with the app:

  dashboard/colombia_dptos.geojson   properties DPTO, nombre        (id = DPTO)
  dashboard/colombia_mpios.geojson   properties MPIO, DPTO, nombre  (id = MPIO)

Boundaries change rarely (new municipalities, e.g. Nuevo Belén de Bajirá), so
this is run by hand when DANE publishes a new MGN year, not by the pipeline:

    python tools/build_geojson.py [--year 2025]
"""

import argparse
import json
from pathlib import Path

import requests

BASE = 'https://geoportal.dane.gov.co/mparcgis/rest/services/MGN{y}/Serv_CapasMGN_{y}/FeatureServer'
OUT = Path(__file__).resolve().parent.parent / 'dashboard'
LAYERS = {
    # name: (layer id, code field, extra fields, simplification in degrees, output file)
    'dptos': (319, 'DPTO_CCDGO', {'DPTO_CNMBRE': 'nombre'}, 0.005, 'colombia_dptos.geojson'),
    'mpios': (317, 'MPIO_CDPMP', {'DPTO_CCDGO': 'DPTO', 'MPIO_CNMBRE': 'nombre'}, 0.002,
              'colombia_mpios.geojson'),
}


def _fetch(s: requests.Session, url: str, code: str, fields: dict, offset: float,
           where: str = '1=1') -> list[dict]:
    """Features of a layer matching `where`. The service rejects paging parameters,
    so municipalities are requested one department at a time (≤ 125 each)."""
    r = s.get(f'{url}/query', params={
        'where': where, 'outFields': ','.join([code, *fields]), 'outSR': 4326,
        'maxAllowableOffset': offset, 'geometryPrecision': 4, 'f': 'geojson'}, timeout=300)
    r.raise_for_status()
    data = r.json()
    if 'error' in data:
        raise SystemExit(f'MGN: {data["error"]}')
    return data.get('features', [])


def _area(ring: list) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))


def _rewind(geom: dict) -> dict:
    """d3 winding for plotly's non-tiled maps: exterior rings clockwise in
    lon/lat, holes counter-clockwise (the opposite of RFC 7946). Otherwise d3
    draws a polygon as 'the whole globe except this shape'."""
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    out = []
    for poly in polys:
        # Rounding to 4 decimals collapses some islets to zero-area rings; d3 cannot
        # tell their inside from their outside and fills the globe, so drop them.
        rings = [r for r in poly if len(r) >= 4 and abs(_area(r)) > 1e-9]
        if not rings or rings[0] is not poly[0]:
            continue
        for k, ring in enumerate(rings):
            if (_area(ring) < 0) != (k == 0):
                ring.reverse()
        out.append(rings)
    if not out:
        raise SystemExit('polígono vacío tras simplificar')
    return {'type': 'Polygon', 'coordinates': out[0]} if len(out) == 1 else         {'type': 'MultiPolygon', 'coordinates': out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=2025)
    year = ap.parse_args().year
    s = requests.Session()
    s.headers['User-Agent'] = 'informe-regional/1.0 (Supersalud)'
    for name, (layer, code, fields, offset, fname) in LAYERS.items():
        url = f'{BASE.format(y=year)}/{layer}'
        if name == 'dptos':
            raw = _fetch(s, url, code, fields, offset)
            dept_codes = sorted(str(f['properties'][code]).zfill(2) for f in raw)
        else:
            raw = [f for d in dept_codes
                   for f in _fetch(s, url, code, fields, offset, where=f"DPTO_CCDGO='{d}'")]
        key = 'MPIO' if name == 'mpios' else 'DPTO'
        feats = []
        for f in raw:
            p = f['properties']
            props = {key: str(p[code]).zfill(5 if key == 'MPIO' else 2),
                     **{out: p[src] for src, out in fields.items()}}
            if 'DPTO' in props:
                props['DPTO'] = str(props['DPTO']).zfill(2)
            feats.append({'type': 'Feature', 'id': props[key], 'properties': props,
                          'geometry': _rewind(f['geometry'])})
        if len(feats) < (1100 if name == 'mpios' else 33):
            raise SystemExit(f'{name}: solo {len(feats)} polígonos — revisar el servicio MGN {year}')
        out = OUT / fname
        out.write_text(json.dumps({'type': 'FeatureCollection', 'features': feats},
                                  separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
        print(f'{out.name}: {len(feats)} polígonos, {out.stat().st_size / 1e6:.2f} MB (MGN {year})')


if __name__ == '__main__':
    main()
