"""Print every prompt for one country, filled with stand-in drawings, without calling the API.

The stand-ins are the reference outline, simplified and stretched sideways (x1.5 as the previous
drawing, x1.25 as the current one), so the C5 scores and the images are real.

Usage:
  python src/preview_prompts.py --country Poland
Writes the images to runs/prompt_preview/<country>/ and prints each message with [image: ...] markers.
"""
import argparse

import yaml
from shapely import affinity

from conditions import slug
from geometry import align, geometry_to_svg, svg_to_geometry
from groundtruth import ROOT, load_countries, load_reference
from metrics import score
from prompts import draw_prompt, judge_message, prompt_text, revise_message
from render import drawing_png


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="Poland")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    country = next((c for c in load_countries() if c["name"].lower() == args.country.lower()), None)
    if country is None:
        raise SystemExit(f"Not in configs/countries.yaml: {args.country}")
    ref = load_reference(country)
    out = ROOT / "runs" / "prompt_preview" / slug(country["name"])

    drawings = {}
    for label, stretch in [("previous", 1.5), ("current", 1.25)]:
        svg = geometry_to_svg(align(affinity.scale(ref, stretch, 1.0)).simplify(0.01))
        geom = svg_to_geometry(svg)
        drawings[label] = (svg, drawing_png(geom, out / f"{label}.png", cfg["render"]), score(geom, ref)["iou"])
    svg, png, iou = drawings["current"]
    prev_png, prev_iou = drawings["previous"][1], drawings["previous"][2]
    critiques = ["- The country is too wide.\n- The northern coast is too straight."]

    messages = [("C0 draw (round 0)", draw_prompt(country))]
    for cond in ("C1", "C2", "C5"):
        messages.append((f"{cond} revise (round 2)",
                         revise_message(cond, country, svg, png, critiques, iou=iou, prev_iou=prev_iou)))
    messages.append(("C1 revise after an invalid reply (round 2)",
                     revise_message("C1", country, None, None, critiques)))
    messages.append(("judge, round 0", judge_message(country, png)))
    messages.append(("judge, round 1 and later", judge_message(country, png, previous_png=prev_png)))

    for title, (pid, parts) in messages:
        print(f"{'=' * 20} {title}   [{pid}]\n{prompt_text(parts)}\n")
    print(f"images in {out}")


if __name__ == "__main__":
    main()
