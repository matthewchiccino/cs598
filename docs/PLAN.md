# Plan

## Deadlines

- **Mon Dec 1:** presentation, 8 min talk + 5 min questions, live demo encouraged.
- **Sun Dec 13, 23:59 ET:** ZIP with code, results and optional README. It must match what we presented.

Decisions live in [DECISIONS.md](DECISIONS.md) (D-xxx below).

## Status

| # | Step | Verify by | Target | Status |
|---|------|-----------|--------|--------|
| 0 | Settle the decisions; write this plan | Read DECISIONS.md | Nov 19 | done |
| 1 | Environment: `requirements.txt`, `.venv`, `configs/default.yaml` skeleton | `python -c "import shapely, svgelements, shapefile, anthropic"` | Nov 20 | done |
| 2 | Ground truth: Natural Earth 1:50m, loader, Web Mercator, scope rule, name map (D-005–007) | Script prints parts and area, and writes reference PNGs for USA, France and Norway | Nov 20 | todo |
| 3 | Evaluator: SVG → geometry, alignment, IoU / Hausdorff / HD95 (D-010–012) | Unit tests: self = 1.0; shifted or scaled = 1.0; perturbed < 1; garbage SVG = invalid | Nov 21 | todo |
| 4 | Country selection: pageviews × complexity → 24 countries (D-009) | `configs/countries.yaml`, plus a 2×2 scatter plot | Nov 22 | todo |
| 5 | LLM wrapper, JSONL log, budget cap, C0 pilot on 5 countries | JSONL rows, scores, and a gallery PNG of round 0 next to the reference | Nov 23 | todo |
| 6 | C1, C2, C3, C5 and the judge; pilot on 5 countries; **freeze prompts** (D-002, D-003, D-008) | Per-round IoU table for the pilot; prompts tagged in git | Nov 24 | todo |
| 7 | Full run: 24 countries × 3 samples × all conditions on the final model | Run finishes under the budget cap; validity rate reported | Nov 25–27 | todo |
| 8 | Analysis: figures for RQ1–RQ4 and the gallery | `analysis/` regenerates every figure from the JSONL | Nov 27–29 | todo |
| 9 | Slides, plus a live demo script (one country, rounds 0–3, scores revealed at the end) | Dry run under 8 min | Nov 29–30 | todo |
| 10 | After Dec 1: paper, ZIP, labelled extensions (C4 memory, lat/lon format, second model) | ZIP contents match the slides | Dec 2–13 | todo |

**Cut line:** if step 6 isn't done by Nov 25, drop C2 and run 16 countries. C0, C1, C3 and C5 alone still answer RQ1 and RQ4.

**Rough call count for step 7:** 24 countries × 3 samples × 13 drawing calls (1 shared + 3 each for C1, C2, C3, C5) ≈ 940. The judge adds a similar number of shorter calls. The pilot in step 5 measures tokens before we commit.

## Contracts (settle before step 5)

### Modules in `src/`

```
groundtruth.py  load_reference(country: dict) -> shapely Geometry   # Web Mercator, scoped, holes dropped
geometry.py     svg_to_geometry(svg: str) -> Geometry | None         # None = invalid output
                align(g: Geometry) -> Geometry                       # centroid to origin, area = 1
metrics.py      score(pred: Geometry | None, ref: Geometry) -> dict  # iou, hausdorff, hd95, valid
render.py       to_png(g: Geometry, path) -> Path                    # what the model sees in C1/C5 and the judge
llm.py          call(model, messages, *, budget) -> Reply            # logs one JSONL row per call
conditions.py   run_trial(country, condition, sample, round0) -> list[Row]
run.py          CLI: config in, JSONL out, resumable
```

### One JSONL row per API call (`runs/<run_id>/calls.jsonl`)

```
run_id, ts, model, condition, country, sample, round,
call_type        # draw | revise | judge
prompt_id        # name + hash of the frozen prompt template
svg, critique    # null where not applicable
judge_rating, judge_verdict   # judge calls only
iou, hausdorff, hd95, valid   # filled by the scorer, never shown to the model except C5
input_tokens, output_tokens, cost_usd
```

## Waiting on the team

- Confirm: D-002 conditions, D-005 projection, D-011 alignment, D-015 model.
- Open: API key owner and the dollar cap (D-015). Team size and who owns which step. Paper format (D-017).
