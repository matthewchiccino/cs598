"""Experiment conditions. Step 5 has round 0 (C0); step 6 adds C1, C2, C3, C5 and the judge (D-002)."""
import re
import time
from pathlib import Path

from geometry import extract_svg, svg_to_geometry
from metrics import score
from prompts import draw_prompt


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def base_row(run: str, llm, condition: str, country: str, sample: int, round_: int, call_type: str) -> dict:
    return {"run_id": run, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": llm.model,
            "condition": condition, "country": country, "sample": sample, "round": round_,
            "call_type": call_type}


def scored_row(row: dict, reply, prompt_id: str, prompt: str, ref, svg_dir: Path) -> dict:
    """Fill in the reply, the extracted SVG and its scores; save the SVG for viewing."""
    svg = extract_svg(reply.text)
    s = score(svg_to_geometry(svg), ref)
    if svg:
        name = f"{slug(row['country'])}__{row['condition']}__s{row['sample']}__r{row['round']}.svg"
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / name).write_text(svg, encoding="utf-8")
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
