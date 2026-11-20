"""Experiment conditions (D-002): round 0 (C0), revision rounds for C1, C2 and C5; step 6c adds C3 and the judge."""
import re
import time
from pathlib import Path

from geometry import extract_svg, svg_to_geometry
from metrics import score
from prompts import draw_prompt, parse_critique, prompt_text, revise_message
from render import drawing_png

REVISED = ("C1", "C2", "C5")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def base_row(run: str, llm, condition: str, country: str, sample: int, round_: int, call_type: str) -> dict:
    return {"run_id": run, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": llm.model,
            "condition": condition, "country": country, "sample": sample, "round": round_,
            "call_type": call_type}


def file_stem(row: dict) -> str:
    return f"{slug(row['country'])}__{row['condition']}__s{row['sample']}__r{row['round']}"


def scored_row(row: dict, reply, prompt_id: str, prompt: str, ref, svg_dir: Path) -> dict:
    """Fill in the reply, the extracted SVG and its scores; save the SVG for viewing."""
    svg = extract_svg(reply.text)
    s = score(svg_to_geometry(svg), ref)
    if svg:
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / f"{file_stem(row)}.svg").write_text(svg, encoding="utf-8")
    return {**row, "prompt_id": prompt_id, "prompt": prompt, "response": reply.text,
            "stop_reason": reply.stop_reason, "svg": svg, "critique": None,
            "judge_rating": None, "judge_verdict": None, **s,
            "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
            "cost_usd": reply.cost_usd, "request_id": reply.request_id}


def round0(llm, budget, country: dict, sample: int, ref, run: str, run_dir: Path) -> dict:
    """C0: draw once from the country name and scope."""
    pid, prompt = draw_prompt(country)
    reply = llm.call(prompt, budget=budget)
    row = base_row(run, llm, "C0", country["name"], sample, 0, "draw")
    return scored_row(row, reply, pid, prompt, ref, run_dir / "svg")


def drawing_image(row: dict, run_dir: Path, render_cfg: dict) -> Path | None:
    """PNG of a logged drawing, rendered once and reused (round 0 is shared by C1 and C5)."""
    geom = svg_to_geometry(row["svg"])
    if geom is None:
        return None
    path = run_dir / "png" / f"{file_stem(row)}.png"
    return path if path.exists() else drawing_png(geom, path, render_cfg)


def check_history(history: list[dict], condition: str, country: str, sample: int):
    """history must be this trial's rows in round order: the shared C0 round 0, then this condition's revisions."""
    if not history:
        raise ValueError("history needs the round-0 row")
    for i, h in enumerate(history):
        want = "C0" if i == 0 else condition
        if (h["condition"], h["country"], h["sample"], h["round"]) != (want, country, sample, i):
            raise ValueError(f"history row {i} is {h['condition']} {h['country']} s{h['sample']} r{h['round']}, "
                             f"expected {want} {country} s{sample} r{i}")


def revise(llm, budget, condition: str, country: dict, sample: int, ref, history: list[dict],
           run: str, run_dir: Path, render_cfg: dict) -> dict:
    """One revision round of C1, C2 or C5 (D-003); returns the row for round len(history).

    history: this trial's logged rows so far, round 0 first. The model sees the latest drawing in the
    condition's form and its earlier critiques; C5 also sees the latest IoU and, from round 2, the one before.
    """
    if condition not in REVISED:
        raise ValueError(f"{condition} has no revision rounds")
    check_history(history, condition, country["name"], sample)
    current = history[-1]
    png = drawing_image(current, run_dir, render_cfg) if condition != "C2" else None
    pid, parts = revise_message(
        condition, country, current["svg"] if current["valid"] else None, png,
        critiques=[h["critique"] for h in history[1:]],
        iou=current["iou"] if condition == "C5" else None,
        prev_iou=history[-2]["iou"] if condition == "C5" and len(history) >= 2 else None)
    reply = llm.call(parts, budget=budget)
    row = base_row(run, llm, condition, country["name"], sample, len(history), "revise")
    row = scored_row(row, reply, pid, prompt_text(parts), ref, run_dir / "svg")
    row["critique"] = parse_critique(reply.text)
    return row
