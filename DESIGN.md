# Design (draft v0, for discussion)

## Research question
Can an LLM improve its own SVG drawings of country borders using only its own feedback (no external tools or ground truth), and does that help less for countries it knows less about?

## Hypotheses
- H1: Self-critique improves over one-shot, but gains plateau after ~2-3 rounds.
- H2: Self-critique beats a compute-matched "just resample k times" baseline (otherwise the critique is not adding anything).
- H3: Cross-country memory of past mistakes helps further.
- H4: Accuracy and self-correction gain both drop for niche countries (the model can't spot errors in shapes it doesn't know).

## Conditions (same model, same prompts, same budget where possible)
| ID | Name | What happens |
|----|------|--------------|
| C0 | One-shot | Draw SVG once. Baseline. |
| C1 | Self-correct (vision) | Render own SVG to PNG, model views it, critiques, revises. N rounds. |
| C2 | Self-correct (text only) | Model re-reads its own SVG code and revises, never sees the render. Isolates the value of seeing. |
| C3 | Resample baseline | Draw k independent one-shots; pick one (self-judged, plus oracle-best as upper bound). Matches compute of C1. |
| C4 | Self-correct + memory | C1, plus a running notes file of its own past mistakes (e.g. "I tend to make islands too large"), carried across countries. |
| C5 | Oracle feedback (optional) | Give the true score/overlay. Upper bound; answers the teammate's "external feedback" question. |

Open decision for the team: is rendering SVG->PNG an "external tool"? Proposal: no, it is just the model looking at its own output, like a person looking at their drawing. State this explicitly in the writeup. C2 covers the stricter reading.

## Task and ground truth
- Prompt: "Draw the outline of <country> as one SVG path in a 0-100 viewBox. Use only what you know."
- Ground truth: Natural Earth 1:110m (or 1:50m) country polygons, public domain. Used for scoring only, never shown to the model (except C5).
- Normalization: project to equirectangular, fit to the bounding box preserving aspect ratio, centered, so the model is judged on shape, not on placement or scale.
- Scenarios to keep simple: include mainland plus major islands only; document how multipart countries are handled.

## Metrics
- Primary: IoU of rasterized filled masks (512px) after normalization.
- Secondary: Chamfer / Hausdorff distance on boundaries (catches thin or wiggly errors IoU misses); SVG validity rate.
- Per-round score curve (round 0..N) for C1/C2/C4.
- Report improvement delta vs C0 and vs C3, with bootstrap CIs over countries and 3 seeds each.

## Country set (~20, customizable via config)
- 10 popular, 10 niche, picked by a familiarity proxy (Wikipedia pageviews or similar).
- Confound: shape complexity. Stratify so both groups span simple and complex shapes (e.g. compare via compactness / vertex count). Avoid popular=complex, niche=blobby.
- Candidate niche: Lesotho, Eswatini, Burkina Faso, Kyrgyzstan, Suriname, Moldova, Slovenia, Djibouti, Togo, Belize. Candidate popular: USA, Italy, Japan, Brazil, India, Australia, France, UK, Egypt, Mexico. (Revise.)

## Framework / stack (choices)
- **Python 3.11+**, plain scripts. No agent framework (LangChain etc.): the loops are ~30 lines and a framework would obscure what we are measuring.
- **Anthropic API** via the official SDK; start with a small/cheap model (Haiku) for iteration, run the final experiments on one stronger model. Optionally add a second provider later for generality. Model name is a config value.
- **Rendering:** `cairosvg` (SVG->PNG) for the model's view and for masks. **Geometry:** `shapely` + `geopandas` for ground truth, `numpy` for IoU/Chamfer.
- **Storage:** every API call logged to JSONL (prompt, response, svg, score, tokens, cost) so runs are resumable, cacheable, and cheap to re-analyze. Seeds and configs saved per run.
- **Config:** one YAML (`configs/default.yaml`): model, countries, conditions, rounds, seeds, budget cap. This is the "make it customizable" requirement.
- **Analysis:** a notebook with pandas + matplotlib for the figures.
- **Cost control:** 20 countries x 3 seeds x ~6 conditions x ~4 calls is about 1.5k calls; fine on a small model. Add a hard budget cap in the runner.

## Repo layout
```
reference/        assignment, idea, chat context
DESIGN.md         this file
configs/          experiment configs (yaml)
data/ground_truth/  natural earth + normalized masks (generated)
src/              groundtruth.py, render.py, metrics.py, llm.py, conditions.py, run.py
runs/             JSONL logs + outputs per run (gitignored)
analysis/         notebooks, figures
```

## Build order (suggested split among 3 people)
1. Ground truth + normalization + metrics (test: score a ground-truth shape against itself = IoU 1.0; against a shifted/scaled copy = still 1.0).
2. LLM wrapper + C0 + C1 end to end on 3 countries (pilot).
3. Remaining conditions + analysis notebook. Run the full set after the pilot shows the metric behaves sensibly.

## Risks
- Models may draw near-identical blobs regardless of country (floor effect). Pilot first.
- Self-judge may be unreliable, so C3's selector matters; report oracle-best too.
- IoU is harsh on thin or archipelagic countries; use the secondary metrics.
- Free-tier quotas: use a paid key with a budget cap.
