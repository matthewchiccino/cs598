"""Step 6b: revision rounds for C1, C2 and C5, driven by a scripted fake client."""
import base64
from types import SimpleNamespace

import pytest
from shapely import affinity

from conditions import revise, round0
from geometry import align, geometry_to_svg
from groundtruth import load_countries, load_reference
from llm import LLM, Budget
from prompts import NO_DRAWING

RENDER = {"size_px": 128, "fill": "#9ab6d6", "stroke": "#1f2d3d"}


class ScriptedClient:
    """Returns the given replies in order and records every request."""

    def __init__(self, replies: list[str]):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))],
                               stop_reason="end_turn", _request_id=f"req_{len(self.requests)}",
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=2000))


@pytest.fixture(scope="module")
def poland():
    spec = next(c for c in load_countries() if c["name"] == "Poland")
    return spec, load_reference(spec)


def drawing(ref, stretch: float) -> str:
    return geometry_to_svg(align(affinity.scale(ref, stretch, 1.0)).simplify(0.01))


def run_trial(condition, replies, poland, tmp_path):
    """Round 0 plus three revisions, as the runner will drive them; returns (rows, client)."""
    spec, ref = poland
    client = ScriptedClient(replies)
    llm, budget = LLM({"name": "claude-haiku-5-5"}, client=client), Budget(1.0)
    rows = [round0(llm, budget, spec, 0, ref, "t", tmp_path)]
    for _ in range(3):
        rows.append(revise(llm, budget, condition, spec, 0, ref, rows, "t", tmp_path, RENDER))
    return rows, client


def blocks(request) -> list[dict]:
    content = request["messages"][0]["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def text_of(request) -> str:
    return "\n".join(b["text"] for b in blocks(request) if b["type"] == "text")


def script(ref) -> list[str]:
    """Round 0 too wide; round 1 better; round 2 critique with no SVG; round 3 exact."""
    return [drawing(ref, 1.5),
            f"<critique>- too wide</critique>\n{drawing(ref, 1.2)}",
            "<critique>- lost the shape</critique>\nSorry, no drawing this time.",
            f"<critique>- fixed</critique>\n{drawing(ref, 1.0)}"]


@pytest.mark.parametrize("condition", ["C1", "C2", "C5"])
def test_three_logged_revisions(condition, poland, tmp_path):
    rows, _ = run_trial(condition, script(poland[1]), poland, tmp_path)
    revs = rows[1:]
    assert [(r["condition"], r["round"], r["call_type"]) for r in revs] == [(condition, i, "revise") for i in (1, 2, 3)]
    assert [r["critique"] for r in revs] == ["- too wide", "- lost the shape", "- fixed"]
    assert rows[1]["iou"] > rows[0]["iou"] and rows[3]["iou"] > 0.98
    assert not rows[2]["valid"] and rows[2]["iou"] == 0 and rows[2]["svg"] is None
    assert all(r["prompt_id"].startswith(f"revise_v1_{condition}:") for r in revs)
    assert all(r["cost_usd"] > 0 and r["request_id"] for r in revs)


def test_c1_shows_the_latest_drawing_and_critiques(poland, tmp_path):
    rows, client = run_trial("C1", script(poland[1]), poland, tmp_path)
    r1, r2, r3 = client.requests[1:]
    image = next(b for b in blocks(r1) if b["type"] == "image")
    assert base64.standard_b64decode(image["source"]["data"]) == (tmp_path / "png" / "poland__C0__s0__r0.png").read_bytes()
    assert rows[0]["svg"] in text_of(r1) and "earlier rounds" not in text_of(r1)
    assert rows[1]["svg"] in text_of(r2) and "Round 1:\n- too wide" in text_of(r2)
    # round 2 had no drawing: round 3 says so, with no image, and keeps both critiques
    assert [b["type"] for b in blocks(r3)] == ["text"]
    assert NO_DRAWING in text_of(r3) and "Round 2:\n- lost the shape" in text_of(r3)
    assert "IoU" not in text_of(r1) + text_of(r2) + text_of(r3)


def test_c2_never_sends_an_image(poland, tmp_path):
    rows, client = run_trial("C2", script(poland[1]), poland, tmp_path)
    assert all(b["type"] == "text" for req in client.requests for b in blocks(req))
    assert rows[0]["svg"] in text_of(client.requests[1])
    assert not (tmp_path / "png").exists()


def test_c5_sees_current_and_previous_iou(poland, tmp_path):
    rows, client = run_trial("C5", script(poland[1]), poland, tmp_path)
    r1, r2, r3 = (text_of(r) for r in client.requests[1:])
    assert f"IoU {rows[0]['iou']:.2f}." in r1
    assert f"IoU {rows[1]['iou']:.2f} (previous drawing: {rows[0]['iou']:.2f})" in r2
    assert NO_DRAWING in r3 and "IoU" not in r3


def test_history_must_match_the_trial(poland, tmp_path):
    spec, ref = poland
    llm = LLM({"name": "claude-haiku-5-5"}, client=ScriptedClient([drawing(ref, 1.0)]))
    r0 = round0(llm, Budget(1.0), spec, 0, ref, "t", tmp_path)
    for bad in ([], [{**r0, "sample": 1}], [r0, {**r0, "condition": "C2", "round": 1}]):
        with pytest.raises(ValueError):
            revise(llm, Budget(1.0), "C1", spec, 0, ref, bad, "t", tmp_path, RENDER)
    with pytest.raises(ValueError):
        revise(llm, Budget(1.0), "C3", spec, 0, ref, [r0], "t", tmp_path, RENDER)
