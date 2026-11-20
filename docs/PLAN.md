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
| 2 | Ground truth: Natural Earth 1:50m, loader, Web Mercator, scope rule, name map (D-005–007) | Script prints parts and area, and writes reference PNGs for USA, France and Norway | Nov 20 | done |
| 3 | Evaluator: SVG → geometry, alignment, IoU / Hausdorff / HD95 (D-010–012) | Unit tests: self = 1.0; shifted or scaled = 1.0; perturbed < 1; garbage SVG = invalid | Nov 21 | done |
| 4 | Country selection: pageviews × complexity → 24 countries (D-009) | `configs/countries.yaml`, plus a 2×2 scatter plot | Nov 22 | done |
| 5 | LLM wrapper, JSONL log, budget cap, C0 pilot on 5 countries | JSONL rows, scores, and a gallery PNG of round 0 next to the reference | Nov 23 | code done, tested with a fake client; pilot waits for an API key |
| 6 | C1, C2, C3, C5 and the judge; pilot on 5 countries; **freeze prompts** (D-002, D-003, D-008) | Per-round IoU table for the pilot; prompts tagged in git | Nov 24 | 6a done (prompts, image input, D-024); 6b done (revision rounds, D-025); 6c done (judge and C3, D-026); 6d done (runner and table, D-027); 6e pilot and freeze (needs the key) |
| 7 | Full run: 24 countries × 3 samples × all conditions on the final model | Run finishes under the budget cap; validity rate reported | Nov 25–27 | todo |
| 8 | Analysis: figures for RQ1–RQ4 and the gallery | `analysis/` regenerates every figure from the JSONL | Nov 27–29 | todo |
| 9 | Slides, plus a live demo script (one country, rounds 0–3, scores revealed at the end) | Dry run under 8 min | Nov 29–30 | todo |
| 10 | After Dec 1: paper, ZIP, labelled extensions (C4 memory, lat/lon format, second model) | ZIP contents match the slides | Dec 2–13 | todo |

**Cut line:** if step 6 isn't done by Nov 25, drop C2 and run 16 countries. C0, C1, C3 and C5 alone still answer RQ1 and RQ4.

**Call count for step 7:** 24 countries × 3 samples × 26 calls per trial = 1,872 at most (`python src/run.py --dry-run`). That is about $1.90 on Haiku 5.5 with guessed tokens (D-027); the pilot measures real tokens before we commit.

## Contracts (settle before step 5)

### Modules in `src/`

```
groundtruth.py  load_reference(country: dict) -> shapely Geometry   # Web Mercator, scoped, holes dropped
geometry.py     svg_to_geometry(svg: str) -> Geometry | None         # None = invalid output
                align(g: Geometry) -> Geometry                       # centroid to origin, area = 1
metrics.py      score(pred: Geometry | None, ref: Geometry) -> dict  # iou, hausdorff, hd95, valid
render.py       to_png(g: Geometry, path) -> Path                    # what the model sees in C1/C5 and the judge
llm.py          LLM(model_cfg).call(content, *, budget) -> Reply     # text, stop_reason, tokens, cost_usd
                RunLog(path).append(row) / .rows() / .spent()        # the runner writes the row after scoring
prompts.py      draw_prompt(country) -> (prompt_id, text)
                revise_message(cond, country, svg, png, critiques, iou, prev_iou) -> (prompt_id, parts)
                judge_message(country, png, previous_png=None) -> (prompt_id, parts)
                parse_critique(text), parse_judge(text) -> (rating, verdict)
                # parts: list of str (text) and Path (PNG); llm.to_content builds the content blocks
render.py       drawing_png(g, path, render_cfg) -> Path                # what C1/C5 and the judge see
conditions.py   round0(llm, budget, country, sample, ref, run, run_dir) -> Row
                revise(llm, budget, cond, country, sample, ref, history, run, run_dir, render_cfg) -> Row
                # history: the trial's logged rows, C0 round 0 first; returns round len(history)
                draw(..., condition="C3", round_=r) -> Row                       # C3 resample
                judge(llm, budget, country, drawing, previous, run, run_dir, render_cfg) -> Row | None
                select_best(drawings, judges) -> {judge_round, judge_iou, oracle_round, oracle_iou}
run.py          CLI: config in, JSONL out, resumable, --dry-run, --conditions
results.py      round_table(rows, rounds), validity_table(rows, rounds); CLI --run <name>
```

### One JSONL row per API call (`runs/<run_id>/calls.jsonl`)

```
run_id, ts, model, condition, country, sample, round,
call_type        # draw | revise | judge
prompt_id        # name + hash of the frozen prompt template
prompt, response, stop_reason, request_id   # full text in and out
svg, critique    # null where not applicable
judge_rating, judge_verdict   # judge calls only
iou, hausdorff, hd95, valid   # filled by the scorer, never shown to the model except C5
input_tokens, output_tokens, cost_usd
```

## Waiting on the team

- Confirm: D-002 conditions, D-005 projection, D-011 alignment, D-015 model.
- Open: API key owner and the dollar cap (D-015). Team size and who owns which step. Paper format (D-017).
