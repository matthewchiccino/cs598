"""SVG text -> shapely geometry, and the alignment applied before scoring (D-011, D-012)."""
import io
import math
import re

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from svgelements import SVG, Close, Line, Move, Path, Shape

CURVE_SAMPLES = 16  # points per curve segment (Bezier, arc)
SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S | re.I)


def extract_svg(text: str) -> str | None:
    """First <svg>...</svg> block in a model reply, or None."""
    m = SVG_RE.search(text or "")
    return m.group(0) if m else None


def _subpath_points(subpath: Path) -> np.ndarray:
    """Vertices of one subpath, with curves sampled, in SVG coordinates (y down)."""
    pts = []
    for seg in subpath:
        if isinstance(seg, Move):
            if seg.end is not None:
                pts.append((seg.end.x, seg.end.y))
        elif isinstance(seg, Close):
            continue
        elif isinstance(seg, Line):
            pts.append((seg.end.x, seg.end.y))
        else:
            ts = np.linspace(0, 1, CURVE_SAMPLES + 1)[1:]
            pts.extend(map(tuple, seg.npoint(ts)))
    return np.asarray(pts, dtype=float).reshape(-1, 2)


def _polygonal(geom) -> list[Polygon]:
    """Polygon parts of any geometry, holes removed."""
    if isinstance(geom, Polygon):
        return [Polygon(geom.exterior)] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _polygonal(g)]
    return []


def svg_to_geometry(svg: str):
    """Union of every closed shape in the SVG, y flipped to point up, holes removed.

    Returns None when nothing with positive area can be read (an invalid output).
    """
    if not svg:
        return None
    try:
        doc = SVG.parse(io.StringIO(svg))
        shapes = [e for e in doc.elements() if isinstance(e, Shape)]
    except Exception:
        return None

    parts = []
    for shape in shapes:
        try:
            subpaths = Path(shape).as_subpaths()
            for sub in subpaths:
                pts = _subpath_points(Path(sub))
                if len(np.unique(pts, axis=0)) < 3:
                    continue
                pts[:, 1] = -pts[:, 1]
                parts.extend(_polygonal(shapely.make_valid(Polygon(pts))))
        except Exception:
            continue

    parts = [p for p in parts if p.area > 0]
    if not parts:
        return None
    merged = shapely.union_all(parts)
    merged_parts = _polygonal(merged)
    if not merged_parts:
        return None
    return shapely.union_all(merged_parts)


def align(geom):
    """Translate the centroid to the origin and scale uniformly to area 1."""
    c = geom.centroid
    moved = affinity.translate(geom, -c.x, -c.y)
    k = 1 / math.sqrt(geom.area)
    return affinity.scale(moved, k, k, origin=(0, 0))


def geometry_to_svg(geom, size: float = 100, margin: float = 5) -> str:
    """Inverse of svg_to_geometry: fit geom (y up) into a size x size viewBox as one <path>."""
    x0, y0, x1, y1 = geom.bounds
    k = (size - 2 * margin) / max(x1 - x0, y1 - y0)
    ox = (size - k * (x1 - x0)) / 2
    oy = (size - k * (y1 - y0)) / 2
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    d = []
    for p in polys:
        xy = np.asarray(p.exterior.coords)[:-1]
        sx = ox + k * (xy[:, 0] - x0)
        sy = size - (oy + k * (xy[:, 1] - y0))
        d.append("M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in zip(sx, sy)) + " Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size:g} {size:g}">'
            f'<path d="{" ".join(d)}" fill="#9ab6d6" stroke="#1f2d3d"/></svg>')
