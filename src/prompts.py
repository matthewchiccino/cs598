"""Prompt templates. Each has an id plus a hash of its text, logged with every call (D-003, D-005).

Prompts freeze at the end of step 6; after that, any change means a new id and a rerun.

A message is a list of parts: str for text, Path for a PNG image. llm.to_content turns it into
content blocks; prompt_text turns it into the text logged in the `prompt` field.
"""
import hashlib
import re
from pathlib import Path

TASK = ("Draw the outline of {name} from memory as an SVG. Draw {scope}. Show the country as it appears "
        "on a standard north-up web map (Web Mercator projection). Use only what you already know; "
        "do not look anything up.")

REQUIREMENTS = """Requirements:
- viewBox="0 0 100 100"
- exactly one <path> element; draw separate landmasses as separate closed subpaths (M ... Z) in that path
- a filled shape with a dark stroke; no other elements, text or labels"""

DRAW_V1 = TASK + "\n\n" + REQUIREMENTS + "\n\nReply with only the SVG code."

# Revision round (D-003): task, the current drawing in the condition's form, earlier critiques.
REVISE_V1 = """Your task: """ + TASK + """

{feedback}
{history}
Find what is wrong with the drawing, using only what you already know about the shape of {name}: proportions, coastline, borders, and missing or extra parts. Write a short critique (at most 5 bullet points) inside <critique></critique> tags. Then give the complete revised SVG. If you find nothing worth fixing, say so in the critique and repeat the same SVG.

""" + REQUIREMENTS + """

Reply with only the <critique> block followed by the SVG code."""

# What each condition is shown of its current drawing (D-002). C1 and C5 also get the PNG, placed first.
FEEDBACK = {
    "C1": "The image shows how your current drawing renders. Its SVG code:\n\n{svg_block}",
    "C2": "The SVG code of your current drawing:\n\n{svg_block}",
    "C5": ("The image shows how your current drawing renders. Its SVG code:\n\n{svg_block}\n\n"
           "Score of this drawing against the true outline: IoU {iou:.2f}{previous}. IoU is the area where "
           "your shape and the true shape overlap, divided by the area they cover together, after both are "
           "moved to the same position and scaled to the same area. 1.00 is a perfect match."),
}
PREVIOUS_IOU = " (previous drawing: {prev_iou:.2f})"
NO_DRAWING = "Your previous reply did not contain an SVG that could be drawn, so there is nothing to show."
SEES_IMAGE = {"C1": True, "C2": False, "C5": True}

# Self-rating probe (D-008): fresh context, renders only, same prompt in every condition.
JUDGE_V1 = """{shown} an attempt to draw the outline of {name} from memory, as it appears on a standard north-up web map (Web Mercator projection). The task was to draw {scope}. Only the shape matters; position and size do not.

Rate how closely the {which}drawing matches the true shape of {name}, from 1 to 10:
1-2: not recognisable as {name}
3-4: a rough shape with a few correct features
5-6: recognisable, with clear errors in proportions or major features
7-8: close, with minor errors
9-10: nearly exact
{compare}
Reply in exactly this format:
<reason>one sentence</reason>
<rating>N</rating>{verdict_line}"""
JUDGE_COMPARE = ("\nAlso say whether the current drawing matches the true shape better than the previous "
                 "drawing, worse, or about the same.\n")
JUDGE_VERDICT_LINE = "\n<verdict>better, worse or same</verdict>"
VERDICTS = ("better", "worse", "same")


def prompt_id(name: str, template: str) -> str:
    return f"{name}:{hashlib.sha1(template.encode()).hexdigest()[:8]}"


def prompt_text(parts) -> str:
    """Text logged for a message; images appear as [image: <file name>]."""
    if isinstance(parts, str):
        return parts
    return "\n\n".join(p if isinstance(p, str) else f"[image: {Path(p).name}]" for p in parts)


def draw_prompt(country: dict) -> tuple[str, str]:
    """(prompt_id, prompt text) for the round-0 drawing."""
    return prompt_id("draw_v1", DRAW_V1), DRAW_V1.format(name=country["name"], scope=country["scope"])


def _history(critiques: list[str | None]) -> str:
    if not critiques:
        return ""
    rounds = [f"Round {i}:\n{c or '(no critique given)'}" for i, c in enumerate(critiques, 1)]
    return "\nYour critiques from earlier rounds, oldest first:\n\n" + "\n\n".join(rounds) + "\n"


def revise_message(condition: str, country: dict, svg: str | None, png: Path | None,
                   critiques: list[str | None], iou: float | None = None,
                   prev_iou: float | None = None) -> tuple[str, list]:
    """(prompt_id, parts) for one revision round of C1, C2 or C5.

    svg/png: the current drawing (None if the last reply had no drawable SVG).
    critiques: critiques from earlier revision rounds, oldest first.
    iou/prev_iou: C5 only; prev_iou from round 2 on.
    """
    pid = prompt_id(f"revise_v1_{condition}", REVISE_V1 + FEEDBACK[condition] + PREVIOUS_IOU + NO_DRAWING)
    if svg is None:
        feedback = NO_DRAWING
    else:
        previous = PREVIOUS_IOU.format(prev_iou=prev_iou) if prev_iou is not None else ""
        feedback = FEEDBACK[condition].format(svg_block=f"```svg\n{svg}\n```", iou=iou or 0.0, previous=previous)
    text = REVISE_V1.format(name=country["name"], scope=country["scope"], feedback=feedback,
                            history=_history(critiques))
    show_image = SEES_IMAGE[condition] and svg is not None
    if show_image and png is None:
        raise ValueError(f"{condition} needs the PNG of the current drawing")
    return pid, ([Path(png), text] if show_image else [text])


def judge_message(country: dict, png: Path, previous_png: Path | None = None) -> tuple[str, list]:
    """(prompt_id, parts) for rating one drawing; with previous_png, also better/worse/same."""
    pid = prompt_id("judge_v1", JUDGE_V1 + JUDGE_COMPARE + JUDGE_VERDICT_LINE)
    compare = previous_png is not None
    text = JUDGE_V1.format(
        shown="The two images show drawings from" if compare else "The image shows",
        name=country["name"], scope=country["scope"], which="current " if compare else "",
        compare=JUDGE_COMPARE if compare else "", verdict_line=JUDGE_VERDICT_LINE if compare else "")
    if compare:
        return pid, ["Previous drawing:", Path(previous_png), "Current drawing:", Path(png), text]
    return pid, [Path(png), text]


def parse_critique(text: str) -> str | None:
    """Text inside <critique> tags. An unclosed tag runs up to the SVG, or to the end of the reply."""
    m = re.search(r"<critique>(.*?)(?:</critique>|<svg\b|$)", text or "", re.S | re.I)
    return (m.group(1).strip() or None) if m else None


def parse_judge(text: str) -> tuple[int | None, str | None]:
    """(rating 1-10, verdict) from a judge reply; None for anything missing or out of range."""
    m = re.search(r"<rating>\s*(\d+)\s*</rating>", text or "", re.I)
    rating = int(m.group(1)) if m and 1 <= int(m.group(1)) <= 10 else None
    v = re.search(r"<verdict>\s*(\w+)\s*</verdict>", text or "", re.I)
    verdict = v.group(1).lower() if v and v.group(1).lower() in VERDICTS else None
    return rating, verdict
