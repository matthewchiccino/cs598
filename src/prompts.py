"""Prompt templates. Each has an id plus a hash of its text, logged with every call (D-003, D-005).

Prompts freeze at the end of step 6; after that, any change means a new id and a rerun.
"""
import hashlib

DRAW_V1 = """Draw the outline of {name} from memory as an SVG. Draw {scope}. Show the country as it appears on a standard north-up web map (Web Mercator projection). Use only what you already know; do not look anything up.

Requirements:
- viewBox="0 0 100 100"
- exactly one <path> element; draw separate landmasses as separate closed subpaths (M ... Z) in that path
- a filled shape with a dark stroke; no other elements, text or labels

Reply with only the SVG code."""


def prompt_id(name: str, template: str) -> str:
    return f"{name}:{hashlib.sha1(template.encode()).hexdigest()[:8]}"


def draw_prompt(country: dict) -> tuple[str, str]:
    """(prompt_id, prompt text) for the round-0 drawing."""
    return prompt_id("draw_v1", DRAW_V1), DRAW_V1.format(name=country["name"], scope=country["scope"])
