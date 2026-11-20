"""Render a shapely geometry to PNG (D-013).

The same function draws reference shapes for figures and, later, the model's own drawing for
conditions C1/C5 and the judge, so the model sees exactly the geometry that is scored.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely.geometry import MultiPolygon
from shapely.geometry.polygon import orient

DEFAULT_FILL = "#9ab6d6"
DEFAULT_STROKE = "#1f2d3d"


def _square_bounds(geom, pad: float) -> tuple[float, float, float, float]:
    """Geometry bounds grown to a centred square with fractional padding."""
    x0, y0, x1, y1 = geom.bounds
    side = max(x1 - x0, y1 - y0) * (1 + 2 * pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def _patch(poly, fill: str, stroke: str, linewidth: float) -> PathPatch:
    # Exterior counter-clockwise, holes clockwise, so nonzero filling leaves holes empty.
    poly = orient(poly, 1.0)
    rings = [poly.exterior, *poly.interiors]
    path = MplPath.make_compound_path(*[MplPath(list(r.coords), closed=True) for r in rings])
    return PathPatch(path, facecolor=fill, edgecolor=stroke, linewidth=linewidth)


def to_png(geom, path, *, bounds=None, size_px: int = 512, fill: str = DEFAULT_FILL,
           stroke: str = DEFAULT_STROKE, linewidth: float = 1.5, pad: float = 0.05) -> Path:
    """Draw geom (y axis up) on a white square canvas and save it as a PNG.

    bounds: (x0, y0, x1, y1) of the canvas; default is the geometry's bounds made square and padded.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = bounds if bounds is not None else _square_bounds(geom, pad)

    dpi = 100
    fig = plt.figure(figsize=(size_px / dpi, size_px / dpi), dpi=dpi)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    for p in polys:
        if not p.is_empty:
            ax.add_patch(_patch(p, fill, stroke, linewidth))
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return path


def drawing_png(geom, path, render_cfg: dict) -> Path:
    """The PNG the model and the judge see of a drawing: the scored geometry, framed to its own bounds."""
    return to_png(geom, path, size_px=render_cfg["size_px"], fill=render_cfg["fill"], stroke=render_cfg["stroke"])
