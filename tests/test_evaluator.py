"""Evaluator checks for step 3: SVG parsing, alignment and metrics (D-010 to D-012)."""
import pytest
from shapely import affinity
from shapely.geometry import Point, Polygon, box

from geometry import align, extract_svg, geometry_to_svg, svg_to_geometry
from groundtruth import load_countries, load_reference
from metrics import score


def svg(d: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="{d}"/></svg>'


# Right angle at bottom-left, in y-up coordinates.
TRIANGLE_UP = Polygon([(0, 0), (10, 0), (0, 10)])
# The same picture in SVG coordinates (y down): bottom edge is y = 100.
TRIANGLE_SVG = svg("M0 100 L100 100 L0 0 Z")


@pytest.fixture(scope="module")
def france():
    spec = next(c for c in load_countries() if c["name"] == "France")
    return load_reference(spec)


# --- parsing -----------------------------------------------------------------------

def test_square_parses_to_area():
    g = svg_to_geometry(svg("M10 10 L90 10 L90 90 L10 90 Z"))
    assert g.area == pytest.approx(80 * 80)


def test_y_axis_is_flipped():
    g = svg_to_geometry(TRIANGLE_SVG)
    assert score(g, TRIANGLE_UP)["iou"] == pytest.approx(1.0)
    mirrored = affinity.scale(TRIANGLE_UP, 1, -1)
    assert score(g, mirrored)["iou"] < 0.9


def test_subpaths_become_parts():
    g = svg_to_geometry(svg("M0 0 L10 0 L10 10 Z M50 50 L60 50 L60 60 Z"))
    assert len(g.geoms) == 2


def test_inner_subpath_fills_hole():
    g = svg_to_geometry(svg("M0 0 L100 0 L100 100 L0 100 Z M40 40 L60 40 L60 60 L40 60 Z"))
    assert g.area == pytest.approx(100 * 100)


def test_arcs_are_sampled():
    circle = svg("M30 50 A20 20 0 1 0 70 50 A20 20 0 1 0 30 50 Z")
    assert score(svg_to_geometry(circle), Point(0, 0).buffer(1, 256))["iou"] > 0.98


def test_self_intersecting_path_is_repaired():
    bowtie = svg_to_geometry(svg("M0 0 L100 100 L100 0 L0 100 Z"))
    assert bowtie is not None and bowtie.is_valid and bowtie.area > 0


def test_polygon_element_is_accepted():
    g = svg_to_geometry('<svg viewBox="0 0 100 100"><polygon points="0,0 50,0 50,50"/></svg>')
    assert g.area == pytest.approx(50 * 50 / 2)


def test_extract_svg_from_reply():
    reply = "Here it is:\n```svg\n" + TRIANGLE_SVG + "\n```\nDone."
    assert extract_svg(reply) == TRIANGLE_SVG
    assert extract_svg("no drawing") is None


@pytest.mark.parametrize("bad", [
    "", "hello", "<svg></svg>", svg(""), svg("M10 10 L20 20"), svg("M10 10 L20 20 L30 30 Z"),
    "<svg><path d='M 1 2 Q'/></svg>",
])
def test_unusable_svg_is_invalid(bad):
    assert svg_to_geometry(bad) is None
    assert score(svg_to_geometry(bad), TRIANGLE_UP) == {
        "valid": False, "iou": 0.0, "hausdorff": None, "hd95": None}


# --- alignment and metrics ------------------------------------------------------------

def test_align_normalises_centroid_and_area(france):
    a = align(france)
    assert a.area == pytest.approx(1.0)
    assert a.centroid.x == pytest.approx(0, abs=1e-9)
    assert a.centroid.y == pytest.approx(0, abs=1e-9)


def test_reference_against_itself_is_perfect(france):
    s = score(france, france)
    assert s["iou"] == pytest.approx(1.0)
    assert s["hausdorff"] == pytest.approx(0, abs=1e-6)


def test_shift_and_uniform_scale_do_not_change_score(france):
    moved = affinity.scale(affinity.translate(france, 3e6, -2e6), 0.37, 0.37)
    s = score(moved, france)
    assert s["iou"] == pytest.approx(1.0)
    assert s["hd95"] == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("change", ["stretch", "rotate", "blob"])
def test_distorted_shapes_score_lower(france, change):
    distorted = {
        "stretch": affinity.scale(france, 1.4, 1.0),
        "rotate": affinity.rotate(france, 25, origin="centroid"),
        "blob": france.convex_hull.buffer(0),
    }[change]
    s = score(distorted, france)
    assert 0 < s["iou"] < 0.97
    assert s["hausdorff"] > 0.01 and s["hd95"] <= s["hausdorff"]


def test_worse_distortion_scores_worse(france):
    mild = score(affinity.scale(france, 1.1, 1.0), france)
    strong = score(affinity.scale(france, 1.6, 1.0), france)
    assert strong["iou"] < mild["iou"]
    assert strong["hd95"] > mild["hd95"]


def test_reference_roundtrip_through_svg(france):
    """Reference -> SVG text in a 0-100 viewBox -> parsed back: the pipeline a model drawing takes."""
    parsed = svg_to_geometry(geometry_to_svg(france))
    s = score(parsed, france)
    assert s["iou"] > 0.995
    assert s["hd95"] < 0.01


def test_unrelated_shape_scores_low(france):
    assert score(box(0, 0, 10, 1), france)["iou"] < 0.5
