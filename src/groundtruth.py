"""Reference country shapes from Natural Earth: lookup, scope, Web Mercator projection.

Decisions: D-005 (projection), D-006 (1:50m data), D-007 (scope), D-012 (holes dropped).

Usage:
  python src/groundtruth.py                          # every country in configs/countries.yaml
  python src/groundtruth.py "United States" France   # selected countries
Writes reference PNGs to runs/references/.
"""
import argparse
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapefile
import shapely
import yaml
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box, shape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHP = ROOT / "data" / "ground_truth" / "ne_50m" / "ne_50m_admin_0_countries"
COUNTRIES_FILE = ROOT / "configs" / "countries.yaml"

EARTH_RADIUS_M = 6378137.0
MAX_LAT = 85.05112878  # Web Mercator latitude limit
DEFAULT_MIN_PART_FRAC = 0.01

# Lookup order: an exact ADMIN match wins over the alternative name fields.
NAME_FIELDS = ("ADMIN", "NAME", "NAME_LONG", "NAME_EN", "FORMAL_EN")


@lru_cache(maxsize=None)
def _index(shp_path: str = str(DEFAULT_SHP)) -> dict:
    """Lower-cased name -> (ADMIN name, lon/lat geometry)."""
    reader = shapefile.Reader(shp_path)
    rows = [(sr.record.as_dict(), shape(sr.shape.__geo_interface__)) for sr in reader.iterShapeRecords()]
    index = {}
    for field in NAME_FIELDS:
        for rec, geom in rows:
            name = (rec.get(field) or "").strip()
            if name:
                index.setdefault(name.lower(), (rec["ADMIN"], geom))
    return index


def lookup(name: str, shp_path: str = str(DEFAULT_SHP)):
    """Return (ADMIN name, lon/lat geometry) for a Natural Earth country name."""
    try:
        return _index(shp_path)[name.lower()]
    except KeyError:
        raise KeyError(f"'{name}' not found in {Path(shp_path).name}") from None


def _parts(geom) -> list[Polygon]:
    """Polygon parts with interior holes removed."""
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    return [Polygon(p.exterior) for p in polys if not p.is_empty]


def _fix_antimeridian(parts: list[Polygon]) -> list[Polygon]:
    """Shift western-hemisphere parts by +360 deg when a country straddles 180 deg."""
    lons = [p.centroid.x for p in parts]
    if max(lons) - min(lons) <= 180:
        return parts
    return [affinity.translate(p, xoff=360) if p.centroid.x < 0 else p for p in parts]


def _mercator(coords: np.ndarray) -> np.ndarray:
    lon = np.radians(coords[:, 0])
    lat = np.radians(np.clip(coords[:, 1], -MAX_LAT, MAX_LAT))
    return np.column_stack([EARTH_RADIUS_M * lon, EARTH_RADIUS_M * np.log(np.tan(math.pi / 4 + lat / 2))])


def _inverse_mercator(coords: np.ndarray) -> np.ndarray:
    lon = np.degrees(coords[:, 0] / EARTH_RADIUS_M)
    lat = np.degrees(2 * np.arctan(np.exp(coords[:, 1] / EARTH_RADIUS_M)) - math.pi / 2)
    return np.column_stack([lon, lat])


def project(geom):
    """lon/lat -> Web Mercator metres."""
    return shapely.transform(geom, _mercator)


def unproject(geom):
    """Web Mercator metres -> lon/lat."""
    return shapely.transform(geom, _inverse_mercator)


def load_reference(country: dict, shp_path: str = str(DEFAULT_SHP)):
    """Scoped, hole-free reference shape for one country spec, in Web Mercator metres.

    country keys: name, ne_name (optional), bbox (optional [lon_min, lat_min, lon_max, lat_max]),
    min_part_frac (optional). Parts are kept when their representative point lies in bbox and their
    area is at least min_part_frac of the kept total.
    """
    _, geom = lookup(country.get("ne_name", country["name"]), shp_path)
    parts = _parts(geom)
    if "bbox" in country:
        region = box(*country["bbox"])
        parts = [p for p in parts if region.contains(p.representative_point())]
    if not parts:
        raise ValueError(f"{country['name']}: no parts inside bbox {country.get('bbox')}")
    parts = [project(p) for p in _fix_antimeridian(parts)]
    total = sum(p.area for p in parts)
    frac = country.get("min_part_frac", DEFAULT_MIN_PART_FRAC)
    parts = [p for p in parts if p.area >= frac * total]
    return shapely.union_all(parts)


def load_countries(path: Path = COUNTRIES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["countries"]


def main():
    from render import to_png

    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="country names from configs/countries.yaml (default: all)")
    ap.add_argument("--out", default=str(ROOT / "runs" / "references"))
    args = ap.parse_args()

    specs = load_countries()
    if args.names:
        wanted = {n.lower() for n in args.names}
        specs = [c for c in specs if c["name"].lower() in wanted]
        missing = wanted - {c["name"].lower() for c in specs}
        if missing:
            raise SystemExit(f"Not in {COUNTRIES_FILE.name}: {', '.join(sorted(missing))}")

    out = Path(args.out)
    for c in specs:
        admin, raw = lookup(c.get("ne_name", c["name"]))
        ref = load_reference(c)
        kept = list(ref.geoms) if isinstance(ref, MultiPolygon) else [ref]
        lon0, lat0, lon1, lat1 = unproject(ref).bounds
        verts = sum(len(p.exterior.coords) - 1 for p in kept)
        png = to_png(ref, out / f"{c['name'].lower().replace(' ', '_')}.png")
        print(f"{c['name']:16s} NE='{admin}'  parts {len(_parts(raw)):3d} -> {len(kept):2d} kept  "
              f"{verts:5d} vertices  lon[{lon0:7.1f},{lon1:7.1f}] lat[{lat0:5.1f},{lat1:5.1f}]  -> {png}")


if __name__ == "__main__":
    main()
