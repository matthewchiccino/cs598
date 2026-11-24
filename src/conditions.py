"""Experiment conditions (D-002): round 0 (C0), revision rounds for C1, C2 and C5, independent resamples
for C3, and the judge that rates every drawing (D-008)."""
import re
import time
from pathlib import Path

from geometry import extract_svg, svg_to_geometry
from metrics import score
from prompts import (draw_prompt, judge_message, parse_critique, parse_judge, prompt_text,
                     revise_message)
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


def reply_row(row: dict, reply, prompt_id: str, prompt: str) -> dict:
    """A call row with the reply filled in and every per-call-type field empty."""
    return {**row, "prompt_id": prompt_id, "prompt": prompt, "response": reply.text,
            "stop_reason": reply.stop_reason, "svg": None, "critique": None,
            "judge_rating": None, "judge_verdict": None,
            "valid": None, "iou": None, "hausdorff": None, "hd95": None,
            "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
            "thinking_tokens": reply.thinking_tokens,
            "cost_usd": reply.cost_usd, "request_id": reply.request_id}


def scored_row(row: dict, reply, prompt_id: str, prompt: str, ref, svg_dir: Path) -> dict:
    """Fill in the reply, the extracted SVG and its scores; save the SVG for viewing."""
    svg = extract_svg(reply.text)
    s = score(svg_to_geometry(svg), ref)
    if svg:
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / f"{file_stem(row)}.svg").write_text(svg, encoding="utf-8")
    return {**reply_row(row, reply, prompt_id, prompt), "svg": svg, **s}


def draw(llm, budget, country: dict, sample: int, ref, run: str, run_dir: Path,
         condition: str = "C0", round_: int = 0) -> dict:
    """One drawing from the country name and scope: C0 round 0, or a C3 resample in rounds 1-3."""
    pid, prompt = draw_prompt(country)
    reply = llm.call(prompt, budget=budget)
    row = base_row(run, llm, condition, country["name"], sample, round_, "draw")
    return scored_row(row, reply, pid, prompt, ref, run_dir / "svg")


def round0(llm, budget, country: dict, sample: int, ref, run: str, run_dir: Path) -> dict:
    """C0: draw once from the country name and scope."""
    return draw(llm, budget, country, sample, ref, run, run_dir)


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


def judge(llm, budget, country: dict, drawing: dict, previous: dict | None, run: str, run_dir: Path,
          render_cfg: dict) -> dict | None:
    """Rate one drawing in a fresh context (D-008); None when the drawing is invalid (nothing to show).

    previous: the drawing one round earlier in the same revision trial (C1, C2, C5 from round 1), for
    the better/worse/same verdict; None for round 0 and for C3 resamples, or if it was invalid.
    The judge row carries the drawing's condition, sample and round, with call_type "judge".
    """
    if previous is not None and drawing["condition"] not in REVISED:
        raise ValueError(f"{drawing['condition']} drawings are rated without a previous drawing")
    png = drawing_image(drawing, run_dir, render_cfg)
    if png is None:
        return None
    previous_png = drawing_image(previous, run_dir, render_cfg) if previous is not None else None
    pid, parts = judge_message(country, png, previous_png)
    reply = llm.call(parts, budget=budget)
    row = base_row(run, llm, drawing["condition"], drawing["country"], drawing["sample"], drawing["round"], "judge")
    rating, verdict = parse_judge(reply.text)
    return {**reply_row(row, reply, pid, prompt_text(parts)), "judge_rating": rating, "judge_verdict": verdict}


def select_best(drawings: list[dict], judges: list[dict]) -> dict:
    """C3 selection among one trial's drawings (C0 round 0 plus the C3 resamples so far).

    Judge pick: the highest judge rating, earliest round on ties. Drawings with no rating (invalid, or an
    unreadable judge reply) are not candidates; with no rated drawing the pick is round 0.
    Oracle: the highest IoU, earliest round on ties; an upper bound no deployed system could reach.
    """
    if len({(d["country"], d["sample"]) for d in drawings + judges}) > 1:
        raise ValueError("select_best takes the rows of one trial")
    by_round = sorted(drawings, key=lambda d: d["round"])
    rating = {j["round"]: j["judge_rating"] for j in judges if j["judge_rating"] is not None}
    rated = [d for d in by_round if d["round"] in rating]
    pick = max(rated, key=lambda d: rating[d["round"]]) if rated else by_round[0]
    oracle = max(by_round, key=lambda d: d["iou"])
    return {"judge_round": pick["round"], "judge_iou": pick["iou"],
            "oracle_round": oracle["round"], "oracle_iou": oracle["iou"]}
