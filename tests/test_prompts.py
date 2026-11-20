"""Step 6a: revise and judge messages, reply parsing, and image content for the API."""
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from llm import LLM, Budget, to_content
from prompts import (NO_DRAWING, judge_message, parse_critique, parse_judge, prompt_text,
                     revise_message)
from render import drawing_png

POLAND = {"name": "Poland", "scope": "the whole country"}
SVG = '<svg viewBox="0 0 100 100"><path d="M10 10 L90 10 L90 90 Z"/></svg>'
CRITIQUES = ["- too wide"]


@pytest.fixture
def png(tmp_path) -> Path:
    return drawing_png(box(0, 0, 2, 1), tmp_path / "current.png",
                       {"size_px": 64, "fill": "#9ab6d6", "stroke": "#1f2d3d"})


def test_drawing_png_is_a_png(png):
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_c1_gets_image_and_svg_but_no_score(png):
    _, parts = revise_message("C1", POLAND, SVG, png, CRITIQUES)
    assert parts[0] == png and len(parts) == 2
    assert SVG in parts[1] and "IoU" not in parts[1]


def test_c2_gets_svg_only(png):
    _, parts = revise_message("C2", POLAND, SVG, png, CRITIQUES, iou=0.5)
    assert len(parts) == 1 and isinstance(parts[0], str)
    assert SVG in parts[0] and "IoU" not in parts[0] and "image" not in parts[0]


def test_c5_gets_image_svg_and_score(png):
    _, parts = revise_message("C5", POLAND, SVG, png, [], iou=0.62)
    assert parts[0] == png and "IoU 0.62." in parts[1] and "previous drawing:" not in parts[1]
    _, parts = revise_message("C5", POLAND, SVG, png, CRITIQUES, iou=0.62, prev_iou=0.5)
    assert "IoU 0.62 (previous drawing: 0.50)" in parts[1]


def test_invalid_drawing_sends_no_image_or_code(png):
    for cond in ("C1", "C2", "C5"):
        _, parts = revise_message(cond, POLAND, None, None, CRITIQUES)
        assert len(parts) == 1 and NO_DRAWING in parts[0] and "```svg" not in parts[0]


def test_image_conditions_need_a_png():
    with pytest.raises(ValueError):
        revise_message("C1", POLAND, SVG, None, [])


def test_critique_history():
    _, first = revise_message("C2", POLAND, SVG, None, [])
    _, later = revise_message("C2", POLAND, SVG, None, ["- too wide", None])
    assert "earlier rounds" not in first[0]
    assert "Round 1:\n- too wide" in later[0] and "Round 2:\n(no critique given)" in later[0]


def test_prompt_ids_per_condition_not_per_country(png):
    ids = {c: revise_message(c, POLAND, SVG, png, [], iou=0.5)[0] for c in ("C1", "C2", "C5")}
    assert len(set(ids.values())) == 3
    other = {"name": "Japan", "scope": "the main landmasses only (leave out small islands)"}
    assert revise_message("C1", other, SVG, png, CRITIQUES)[0] == ids["C1"]


def test_judge_message(png, tmp_path):
    pid, parts = judge_message(POLAND, png)
    assert parts == [png, parts[1]] and "<rating>" in parts[1] and "<verdict>" not in parts[1]
    prev = tmp_path / "previous.png"
    pid2, parts = judge_message(POLAND, png, previous_png=prev)
    assert pid2 == pid
    assert parts[:4] == ["Previous drawing:", prev, "Current drawing:", png] and "<verdict>" in parts[4]
    assert "IoU" not in parts[4] and "<svg" not in parts[4]


def test_parse_critique():
    assert parse_critique("<critique>\n- too wide\n</critique>\n<svg/>") == "- too wide"
    assert parse_critique("<svg/>") is None


@pytest.mark.parametrize("text,expected", [
    ("<reason>ok</reason><rating>7</rating><verdict>Better</verdict>", (7, "better")),
    ("<rating> 10 </rating>", (10, None)),
    ("<rating>11</rating><verdict>improved</verdict>", (None, None)),
    ("seven", (None, None)),
])
def test_parse_judge(text, expected):
    assert parse_judge(text) == expected


def test_prompt_text_marks_images(png):
    assert prompt_text(["a", png, "b"]) == "a\n\n[image: current.png]\n\nb"


def test_parts_become_image_and_text_blocks(png):
    blocks = to_content([png, "hello"])
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(blocks[0]["source"]["data"]) == png.read_bytes()
    assert blocks[1] == {"type": "text", "text": "hello"}
    assert to_content("plain") == "plain"


def test_llm_sends_the_image(png):
    sent = []

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                sent.append(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                                       usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    _, parts = revise_message("C1", POLAND, SVG, png, [])
    LLM({"name": "claude-haiku-5-5"}, client=Client()).call(parts, budget=Budget(1.0))
    assert [b["type"] for b in sent[0]["messages"][0]["content"]] == ["image", "text"]
