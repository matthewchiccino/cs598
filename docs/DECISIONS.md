# Decisions

Newest first. Each entry says what was decided, why, and its status:

- **settled**: we build on it now.
- **confirm**: settled for this branch; the team should confirm it.
- **open**: not decided yet.

Where an entry differs from `DESIGN.md` (draft v0), it says so. This file takes precedence.

Sources: `DESIGN.md`, `reference/`, the two design chats (Claude, ChatGPT), and the lecture 6 final-project slides.

---

## D-017 Paper format — open
The course grades the presentation and a ZIP (code plus results, optional README). The research-paper report is our own addition. It is written Dec 2–13 from results already presented. The format (Overleaf LaTeX or Markdown to PDF) is not decided. It does not block anything before Dec 1.

## D-016 What is presented Dec 1 is what is in the ZIP — settled
The ZIP gets full marks "if the submitted materials match what the team described in its presentation" (slide 3). After Dec 1 we only add work labelled as an extension, such as C4 memory or a second model. Results we already presented are not reworked.

## D-015 Model, sampling and budget — confirm
- **Development and pilot:** `claude-haiku-5-5`.
- **Final runs:** one stronger vision-capable model (`claude-sonnet-5-5`), picked after the pilot shows its cost.
- **Model setup:** model name is a config value. Temperature is the API default (1.0). Extended thinking is off in every condition.
- **Samples:** there is no seed parameter. "3 seeds" means 3 independent samples per country × condition.
- **Logging:** every call is logged to JSONL (prompt, response, tokens, cost), so analysis never repeats a call.
- **Budget:** the runner enforces a hard budget cap.
- **Open:** who owns the API key, and the dollar cap.

Why: the Anthropic SDK is already used in `src/draw_test.py`. Keeping one provider fixed keeps the comparison clean. A second provider is an extension.

## D-014 Python environment and dependencies — settled
- **Python and venv:** Python 3.13 in a `.venv`. On this machine `python` resolves to 3.13.15.
- **Dependencies:** `anthropic`, `shapely`, `svgelements`, `pyshp`, `numpy`, `matplotlib`, `pyyaml`, `pandas`.
- **Dropped (differs from DESIGN.md):** `cairosvg` and `geopandas`.
  - `cairosvg` needs the native Cairo library, which is hard to install on Windows. The team works on both Windows and macOS.
  - `pyshp` reads the shapefile with no GDAL dependency.

## D-013 Rendering what the model sees — settled
SVG path → parsed with `svgelements` → shapely geometry → PNG drawn with matplotlib. The PNG has a fixed size, fill colour and stroke, and no axes. The model is shown a render of exactly the geometry we score.

## D-012 Scoring geometry from the SVG — settled
Each closed subpath of the model's `<path>` becomes a polygon. All polygons are unioned. SVG y points down, so it is flipped.

Interior holes are dropped in both the model output and the reference. Example: the hole Lesotho makes in South Africa. Invalid polygons are repaired with `make_valid`. A reply with no parsable path counts as an invalid output: it counts toward the validity rate and gets IoU 0.

## D-011 Alignment before scoring — settled (differs from DESIGN.md)
Both shapes are translated so their centroids sit at the origin. Then they are scaled uniformly to equal area. There is no rotation and no non-uniform stretch.

Why: fitting to a bounding box (DESIGN.md) moves the whole shape if one island is misplaced. Equal-area scaling keeps aspect-ratio and orientation errors visible. The metric judges shape, not placement or size.

Unit test: a reference scored against a shifted and scaled copy of itself gives IoU = 1.0.

## D-010 Metrics — settled
- **Primary:** IoU of the two aligned polygons (exact shapely area, no rasterising).
- **Boundary:** Hausdorff distance and HD95 (95th percentile of boundary point distances). Both are divided by √(reference area), so they compare across countries. Boundaries are densified before sampling.
- **Validity rate:** share of replies that yield a usable polygon.
- **Per round:** gain over round 0 (ΔIoU), and regression rate (share of revisions that lower IoU).
- **Calibration:** Spearman correlation between the judge's rating (D-008) and true IoU, and how often its better/worse/same verdict is right.

The metrics are reported separately, never combined into one weighted score.

## D-009 Country set — settled (procedure), open (final list)
- **Size:** 24 countries in a 2×2 grid of familiarity × shape complexity, 6 per cell.
- **Familiarity:** English Wikipedia pageviews for the country article over the last 12 months. In the write-up this is called "estimated training exposure".
- **Complexity:** computed on the 1:50m reference after the scope rule (D-007). Measures: 1 − isoperimetric quotient, the convex hull deficit, and the number of parts. The split is at the median of each axis.
- **Excluded:**
  - countries missing from 1:50m
  - archipelagos whose scope can't be stated in one line (Indonesia, Philippines)
  - microstates
- **Never used as a familiarity measure:** the one-shot score. It is the outcome, so using it as an input would make the analysis circular.

Why: DESIGN.md's candidate lists confound popularity with complexity. At 1:110m the "niche" candidates have 11–39 vertices (Lesotho 12, Eswatini 11). The "popular" ones have 44–447 (USA 447, Australia 241).

## D-008 Self-rating probe ("judge") — settled (new, not in DESIGN.md)
After every drawing is produced, a separate fresh-context call shows the model the PNG. It asks for a 1–10 accuracy rating. From round 1 on, it also asks whether the drawing is better, worse or the same as the previous one.

The judge is a measuring instrument. Its output never goes back into the drawing loop, except in C3, where it picks the best of k samples. It uses the same prompt in every condition.

Why: both chats recommend measuring "does it know when it's wrong". C3 also needs a selector.

## D-007 Territory scope per country — settled
Each country in `configs/countries.yaml` has a scope string. The same string goes into the prompt and selects the reference parts. Examples:

- "the contiguous United States (lower 48 states only)"
- "metropolitan France including Corsica"
- "mainland Norway, excluding Svalbard"

Why: at 1:110m, USA has 10 parts reaching −171.8° (Alaska, Hawaii). France reaches −54.5° (French Guiana). Norway reaches 80.7°N (Svalbard). Unscoped, these distort the reference shape.

## D-006 Ground-truth data — settled (differs from DESIGN.md)
Natural Earth 1:50m admin-0 countries are used for scoring and complexity. The 1:110m files already in the repo stay for quick tests.

Why: 1:110m is missing 30 of the 195 names that `draw_test.py` accepts. Its small countries are crude polygons (Djibouti has 15 vertices). Names also need a mapping, for example "Cote d'Ivoire" is "Ivory Coast" in Natural Earth.

## D-005 Projection — settled (differs from DESIGN.md)
References are projected to Web Mercator. The prompt says the outline should look as it does "on a standard north-up web map".

Why: Web Mercator matches the maps the model most likely learned from. It keeps the shape of a single country correct locally. Plain equirectangular (DESIGN.md) squashes high-latitude countries sideways.

## D-004 Output format — settled
One `<svg viewBox="0 0 100 100">` with a single `<path>`. Several closed subpaths (`M … Z M … Z`) are allowed for islands. The reply contains the SVG only. This is unchanged from `draw_test.py`.

Asking for latitude/longitude points would separate "doesn't know the shape" from "can't write SVG coordinates". That is an extension (C0 only), if there is time after Dec 1.

## D-003 Revision loop — settled
- **Rounds:** fixed at 3 (round 0 plus 3 revisions). There is no early stopping.
- **Calls:** each revision is one call that returns a short critique and the full revised SVG. The critique is logged.
- **Context:** each call carries the task, the current drawing (in the condition's form), and the previous critiques. It does not carry earlier drawings.

Why: a fixed number of rounds makes the conditions comparable and keeps compute matched with C3. One call per round halves the cost compared with separate critique and revise calls.

## D-002 Conditions in scope for Dec 1 — settled (differs from DESIGN.md)
All conditions in a trial start from the same round-0 drawing. C0 is that drawing.

| ID | What the model gets each round |
|----|--------------------------------|
| C0 | Nothing. Round 0 only. |
| C1 | A PNG render of its own drawing, plus its SVG |
| C2 | Its own SVG code only |
| C3 | Nothing. It draws 3 more independent samples (4 in total). The judge picks one. The oracle-best is also reported as an upper bound. |
| C5 | Same as C1, plus the IoU of the current drawing (and of the previous one, from round 2). It gets a number only, never an overlay. |

C4 (memory across countries) is a stretch goal after Dec 1. It depends on the order countries are drawn in, so it can't run in parallel with the rest.

Why: four draws per trial in C1, C2, C3 and C5 match their compute. A scalar score answers "does real feedback help" without showing the true shape.

## D-001 Research question and framing — settled
**Title (working):** Can agents correct what they don't know? Intrinsic self-correction on drawing country outlines from memory.

- **RQ1:** Does self-correction beat compute-matched resampling (C1/C2 vs C3)?
- **RQ2:** Does seeing its own render help more than rereading its code (C1 vs C2)?
- **RQ3:** How do accuracy and self-correction gain vary with familiarity and complexity?
- **RQ4:** Does the model's self-rating track true accuracy (judge calibration)?

C5 is the reference point for how much real feedback adds.

Rendering its own output is described as "self-correction without external ground-truth feedback". C2 covers the stricter reading, where the model sees no render at all.

For the "why not just Claude Code?" slide: the draw → look → fix loop is what a general-purpose agent does. We measure when that loop works.
