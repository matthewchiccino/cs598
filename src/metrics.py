"""Shape scores between a model drawing and a reference (D-010).

Both shapes are aligned first (centroid at origin, area 1), so distances are in units of
sqrt(reference area) and compare across countries.
"""
import numpy as np
import shapely

from geometry import align

DEFAULT_BOUNDARY_SAMPLES = 1000


def boundary_points(geom, n: int) -> np.ndarray:
    """About n points spaced evenly along all boundary rings of geom."""
    lines = list(getattr(geom.boundary, "geoms", [geom.boundary]))
    total = sum(line.length for line in lines)
    pts = []
    for line in lines:
        k = max(2, round(n * line.length / total))
        pts.append(shapely.line_interpolate_point(line, np.linspace(0, line.length, k, endpoint=False)))
    return np.concatenate(pts)


def score(pred, ref, boundary_samples: int = DEFAULT_BOUNDARY_SAMPLES) -> dict:
    """iou, hausdorff, hd95 and valid for a predicted geometry (None = invalid output).

    hausdorff: largest boundary-to-boundary distance in either direction (sampled).
    hd95: 95th percentile of the pooled distances from both directions.
    """
    if pred is None or pred.is_empty or pred.area <= 0:
        return {"valid": False, "iou": 0.0, "hausdorff": None, "hd95": None}

    a, b = align(pred), align(ref)
    union = shapely.union(a, b).area
    iou = shapely.intersection(a, b).area / union if union > 0 else 0.0

    pa, pb = boundary_points(a, boundary_samples), boundary_points(b, boundary_samples)
    d_ab = shapely.distance(pa, b.boundary)
    d_ba = shapely.distance(pb, a.boundary)
    pooled = np.concatenate([d_ab, d_ba])
    return {
        "valid": True,
        "iou": float(iou),
        "hausdorff": float(pooled.max()),
        "hd95": float(np.percentile(pooled, 95)),
    }
