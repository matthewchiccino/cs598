# Decisions

Newest first. Each entry says what was decided, why, and its status:

- **settled**: we build on it now.
- **confirm**: settled for this branch; the team should confirm it.
- **open**: not decided yet.

Where an entry differs from `DESIGN.md` (draft v0), it says so. This file takes precedence.

Sources: `DESIGN.md`, `reference/`, the two design chats (Claude, ChatGPT), and the lecture 6 final-project slides.

---

## D-032 Sonnet 5.5 thinks even with `between_tools`; we keep it and log thinking tokens — settled (refines D-022, D-031)
- **Finding (Sonnet pilot, Nov 24):** `pilot_sonnet` (3 countries × 1 sample, 78 calls, $0.84) sent `thinking: {type: "between_tools"}` at effort `high`, which the API reference describes as "no extended thinking". A diagnostic repeat of Poland's round-0 call returned an empty `thinking` block, and `usage.output_tokens_details.thinking_tokens` was 3,406 of 3,898 output tokens.
- **Size:** 9 of 39 Sonnet drawing calls have under 1 reply character per output token, mostly round-0 and C3 draws of Poland and Japan. That signature means hidden thinking. Haiku 5.5 (`disabled`) shows none in 130 calls.
- **Consequences:**
  - Sonnet's thinking is uneven across conditions. Fresh draws think more than revisions, which biases the drawings revisions start from against the revisions themselves.
  - Sonnet's full-run cost projects to about $20, above the cap.
  - The log doesn't record thinking tokens: `scored_row` keeps text blocks and total output tokens only.
- **Options:**
  1. Test whether a lower effort with `between_tools` stops the thinking.
  2. Run Sonnet with adaptive thinking on purpose, log thinking tokens, and compare it with Haiku `--thinking` (D-023).
  3. Keep Haiku as the main thinking-off model and make Sonnet an extension.
- **Either way:** log `thinking_tokens` per call before any main run.
- **Decision (Nov 24):** keep Sonnet at `between_tools` and effort `high`, as in the pilot. The team handles the cost question separately (the $20 cap may need raising).
- **Logging:** every row now has `thinking_tokens` from `usage.output_tokens_details`. It is part of `output_tokens`, and null when the API sends no breakdown. Haiku 5.5 reports 0, checked with one real call. The two pilot logs predate the field.
- **Analysis use:**
  - share of calls that thought, per condition and round;
  - revision gains recomputed on calls that did not think, so the confound is measured;
  - IoU of drawings that came after thinking against those that did not.

  The reasoning text is not available: with `between_tools` the `thinking` block is empty, and the API rejects a `display` field.

## D-031 Main run on Sonnet 5.5, Haiku 5.5 as a second model — settled (resolves D-015's model choice)
- **Main run:** `claude-sonnet-5-5`, thinking off (`between_tools`, D-022), the default in `configs/default.yaml`. `python src/run.py` writes `runs/main_claude-sonnet-5-5/`.
- **Second model:** `python src/run.py --model claude-haiku-5-5` writes `runs/main_claude-haiku-5-5/`. Both models run thinking-off with the same frozen prompts (`prompts-v1`), so "does a bigger model self-correct better?" is a fair comparison.
- **Before the full run:** a Sonnet pilot (`--run pilot_sonnet`, 2–5 countries × 1 sample). It checks that `between_tools` keeps thinking off on the real API, measures Sonnet's tokens for the cost estimate, and checks that its replies parse.
- **Cost:** at the Haiku pilot's token counts, Sonnet is about $9 and Haiku about $0.50 for the full run. The $20 cap stays.
- **Shared data:** each main run's `calls.jsonl` and `config.json` are tracked in git (`.gitignore` exception). SVGs, PNGs and the gallery stay local because they regenerate from the log. Pilots stay local.

Why: Haiku's round-0 drawings fell below the disc floor for 4 of 5 pilot countries, so a stronger model makes the test of self-correction fairer. Running Haiku as well costs little and adds a model-size comparison.

## D-030 One folder per model and run, named `main_<model>` — settled (refines D-023, D-029)
- **Default run name:** `main` (`run_name` in `configs/default.yaml`). A full run on Sonnet 5.5 therefore writes to:
  - `runs/main_claude-sonnet-5-5/`: the call log, config, SVGs, PNGs and gallery;
  - `analysis/main_claude-sonnet-5-5/`: figures and CSV tables.

  Haiku gets the same layout under `main_claude-haiku-5-5`.
- **Pilots and tests** pass `--run` with their own name (e.g. `--run pilot_sonnet`), so they never land in a main folder. The existing pilot stays at `runs/pilot_claude-haiku-5-5/`.
- **No mixing:** a run folder refuses a second model or thinking setting (D-023).
- **Inside a run, files are not split by condition.** The condition is part of each file name (`poland__C1__s0__r2.svg`) and a column in `calls.jsonl`. The analysis charts compare conditions, so they draw from one log.

Why: keeping each model's data and charts apart prevents mixing them in figures, and the layout stays the one D-029 already describes.

## D-029 Analysis: intervals, paired gains and judge scoring — confirm (refines D-010, D-019)
- **Script:** `python src/analysis.py --run <run>` reads `runs/<run>/calls.jsonl` and writes every figure and table to `analysis/<run>/`. Nothing is computed by hand, so a rerun regenerates the report numbers.
- **Unit of analysis is the country.** The 3 samples of a country are averaged first, then a bootstrap resamples the 24 countries (2,000 resamples, fixed seed) for 95% intervals. Samples of one country share its difficulty, so treating 72 trials as independent would make the intervals too narrow.
- **Gains are paired within a trial:** each curve's IoU at round k minus the shared round-0 IoU of the same trial. RQ1 and RQ2 use paired differences of those gains: C1 − C3 (judge pick), C2 − C3 (judge pick), C1 − C2, and C5 − C1.
- **The per-round chart plots gains, not levels.** Countries differ far more than conditions do, so intervals on mean IoU span the whole chart and hide the effect. Level curves are still drawn, without intervals.
- **RQ3:** per cell, the one-shot floor-normalised IoU (D-019) and the gain at round 3 for each condition. With 6 countries per cell these intervals are wide; the write-up reports them as descriptive.
- **RQ4:** Spearman between rating and IoU, pooled and averaged within country. The within-country value is the stricter test, because the pooled value rises just from the judge telling easy countries from hard ones. Verdict accuracy compares better / worse / same with the true IoU change, where a change under **0.02** counts as "same".
- **Spearman** is computed as Pearson on average ranks, which avoids adding scipy.

Why: the country-level bootstrap and paired gains match how the experiment varies. The 0.02 tolerance is a placeholder, not measured. It should be checked against how much IoU moves when C1 repeats the same SVG ("unchanged" in `regressions.csv`) and against the pilot. Changing it only rescores the verdicts (`SAME_TOL` in `src/analysis.py`).

## D-028 Pilot result, critique parsing, and the prompt freeze — settled (refines D-024)
- **Pilot (Nov 20):** Haiku 5.5, 5 countries × 2 samples, all conditions. It made 260 calls for $0.064. All 260 stopped normally (`end_turn`), with no refusals and no invalid drawings. The log is `runs/pilot_claude-haiku-5-5/`.
- **Parsing fix:** in 11 of 90 revisions the model opened `<critique>` and never closed it before the SVG. Those critiques were logged as null, and the next rounds said "(no critique given)". In 1 reply the SVG sat inside the tags, so the logged critique contained the SVG code.
  - `parse_critique` now reads up to `</critique>`, the start of the SVG, or the end of the reply, whichever comes first.
  - On the pilot replies it recovers all 90 critiques and leaves the other 78 unchanged.
  - The prompt text is unchanged. The pilot log is kept as it ran.
- **Frozen prompts** (tag `prompts-v1`): `draw_v1:be1788da`, `revise_v1_C1:9b428766`, `revise_v1_C2:a2bf7061`, `revise_v1_C5:56572ab6`, `judge_v1:fc419ab3`. Any change from here means a new id and a rerun (D-003).

Why: the parser change only recovers text the model already wrote, so freezing the prompts doesn't need a second pilot.

## D-027 Runner order, cost estimate and the per-round table — settled (refines D-022, D-026)
- **Order within a trial (country × sample):**
  1. the round-0 drawing and its judge call;
  2. for each revision condition in turn (C1, C2, C5), rounds 1–3 as revise then judge;
  3. C3 rounds 1–3 as draw then judge.

  Trials run country by country. Every call is keyed by (condition, country, sample, round, call_type) and skipped if already logged. A budget stop mid-trial therefore resumes at the next missing call.
- **`--conditions`** picks a subset; round 0 always runs. The config default is all of C0, C1, C2, C3 and C5.
- **Dry run:** prints the number of calls still to make and an estimated cost. The count is an upper bound, since invalid drawings skip their judge call.
  - Tokens per call type come from the run's own log once it has rows. Until then they come from guesses in `run.GUESS_TOKENS`: draw 250 in / 3000 out, revise 4000 / 3200, judge 900 / 80.
  - Full experiment: 1,872 calls, about $1.90 on Haiku 5.5 with the guessed tokens. The pilot replaces the guesses.
- **Per-round table** (`src/results.py`, also printed at the end of every run):
  - Mean IoU per condition and round, with an invalid drawing counted as 0, plus the share of valid drawings.
  - Round 0 is the shared C0 drawing in every row.
  - C3 appears twice per round k: the judge's pick among rounds 0..k, and the best by IoU among them.

Why: a fixed order with per-call keys makes runs reproducible and safe to stop. Counting invalid drawings as 0 keeps a model that stops producing SVG from looking better.

## D-026 Judge calls and C3 selection — confirm (refines D-002, D-008)
- **One judge call per valid drawing,** using the same model. The judge row repeats the drawing's condition, sample and round, with `call_type: "judge"`. It fills `judge_rating` and `judge_verdict` and leaves the score fields null. The round-0 drawing is rated once, under C0.
- **Invalid drawings get no judge call,** since there is nothing to render. Analysis treats them as unrated.
- **Better / worse / same** is asked only in revision trials (C1, C2, C5) from round 1, against the drawing one round earlier. If that drawing was invalid, the call asks for the rating alone.
- **C3 resamples are rated alone.** Independent samples have no "previous" to compare with.
- **C3 resamples** use the round-0 draw prompt unchanged, logged as condition C3, rounds 1–3, `call_type: "draw"`.
- **C3 selection** (`conditions.select_best`) runs over round 0 plus the resamples up to a given round:
  - **Judge pick:** the highest rating; ties go to the earliest round. Unrated drawings are not candidates. If nothing was rated, the pick is round 0, which is what the model returns with no selection.
  - **Oracle:** the highest IoU, ties to the earliest round. It is reported as an upper bound only.
  - C3's value "at round k" is the pick among rounds 0..k. That gives the curve that is compute-matched with the revision conditions.

Why: rating only what can be shown keeps the judge on equal footing in every condition. Ties going to the earliest round favour the cheaper answer and make the pick deterministic.

## D-025 Revision state comes from the log — settled (refines D-003)
- **`conditions.revise`** makes one call. Its input is the trial's logged rows so far: the shared C0 round 0, then that condition's earlier revisions. Resuming mid-trial therefore needs nothing beyond `calls.jsonl`. It refuses rows from another trial, a wrong condition or a gap in the rounds.
- **"Current drawing" means the latest one,** even if it scored worse. The model is never shown its best earlier drawing; choosing among drawings is what C3 measures.
- **After an invalid round,** the next round gets the no-drawing message (D-024). It does not fall back to the last valid drawing, and C5 shows no score that round. The critiques, including the one from the invalid round, still carry forward.
- **PNGs** go to `runs/<run>/png/<country>__<condition>__s<sample>__r<round>.png`, rendered once. C1 and C5 share the round-0 image.

Why: the log is the single source of truth, so a crash or budget stop loses nothing. Showing the latest drawing is what "self-correct" means in D-001.

## D-024 Revise and judge prompts — confirm (refines D-002, D-003, D-008, D-013)
- **Revise prompt `revise_v1_<condition>`** (`src/prompts.py`). Each round repeats the round-0 task sentence, shows the current drawing in the condition's form, and lists earlier critiques oldest first. It then asks for a critique of at most 5 bullets in `<critique>` tags, followed by the complete revised SVG with the same requirements as `draw_v1`.
- **Keeping a drawing is allowed:** "If you find nothing worth fixing, say so in the critique and repeat the same SVG." A prompt that forces a change every round would build in drift and blur the RQ1 answer.
- **What each condition sees:**
  - C1: the PNG (placed before the text) and the SVG code.
  - C2: the SVG code only.
  - C5: the same as C1, plus "IoU 0.62 (previous drawing: 0.50)" and one sentence defining IoU, including that position and size are factored out (D-011).
- **Invalid current drawing:** the model gets "Your previous reply did not contain an SVG that could be drawn", with no image, code or score, and the round still runs.
- **Render the model sees:** the scored geometry (D-013), framed to its own bounds (`render.drawing_png`, 512 px, config colours). The frame is not the SVG viewBox, because a reply's `width`/`height` attributes can rescale its coordinates.
- **Judge prompt `judge_v1`:** a fresh context with renders only, never the SVG or a score. It has the country name, the scope sentence, "only the shape matters; position and size do not", and a 1–10 scale with anchors at 1–2, 3–4, 5–6, 7–8 and 9–10. The reply is `<reason>` (one sentence) and `<rating>`. From round 1 the judge also sees the previous drawing, labelled and placed first, and adds `<verdict>` better / worse / same.
- **Parsing:** a missing critique is logged as null and shown in later rounds as "(no critique given)". A judge rating outside 1–10, or a verdict outside the three words, is logged as null.
- **Preview:** `python src/preview_prompts.py --country <name>` prints every message, with stand-in drawings and real scores, without calling the API.

Why: one shared frame keeps the conditions differing only in the feedback block. The anchored scale and fixed tags make judge replies parseable and comparable across conditions.

## D-023 Choosing the model per run, and Opus needs thinking on — confirm (refines D-015, D-022)
- **`--model`:** `src/run.py --model <id>` overrides `model.name` in the config. The run name defaults to `<run_name>_<model>`, so each model writes its own log. A run started with one model or thinking setting refuses to continue with another.
- **`--thinking`:** leaves thinking on, which means adaptive thinking (no `thinking` field is sent).
  - It's **required for `claude-opus-5-5`**, which rejects every way of turning thinking off. Without the flag the runner stops and explains why.
  - Thinking tokens are billed as output, so Opus runs cost more than the per-call estimates in D-015.
- **Why it matters:** the initial demo (Matthew's) compared Haiku and Opus. Thinking-on and thinking-off runs are not comparable, because thinking is a form of hidden self-revision.
  - The main experiment runs thinking-off on Sonnet 5.5, with Haiku 5.5 as a second thinking-off model (D-031).
  - A Haiku vs Opus comparison runs **both** models with `--thinking`, and is reported separately as a model-comparison extension.
- **Prices known to the runner:** Haiku 5.5, Sonnet 5.5 and Opus 5.5. Any other model ID is refused until its price is added to `PRICES` in `src/llm.py`.

## D-022 API request settings and the draw prompt — settled (refines D-015)
- **No `temperature`:** current models reject sampling parameters (`temperature`, `top_p`, `top_k`), so we send none. Independent samples come from repeated calls (D-015).
- **Thinking off:** we keep D-015's thinking-off rule, and the request field differs by model:
  - Haiku 5.5: `{type: "disabled"}`
  - Sonnet 5.5: `{type: "between_tools"}`. Its `disabled` returns a 400, and with no tools in the request no thinking happens.
  - Opus 5.5 can't turn thinking off, so `llm.thinking_off` refuses it.
- **Effort:** set explicitly to `high` (`output_config.effort`). The default differs by model (Haiku `medium`, Sonnet `high`), so leaving it unset would change it silently when we switch models.
- **`max_tokens`:** 16000, non-streaming.
- **Prices for the cost log** (USD per million input / output tokens): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10.
- **Refusals:** returned as normal rows with `stop_reason: "refusal"`. They count as invalid outputs, and their cost is still logged.
- **Draw prompt `draw_v1`** (`src/prompts.py`): country name, scope sentence, "Show the country as it appears on a standard north-up web map (Web Mercator projection)", from memory, `viewBox 0 0 100 100`, one `<path>` with a closed subpath per landmass, SVG only. It can change until prompts freeze at step 6. Every row logs `prompt_id` (name + hash) and the full prompt text.
- **Logging:** the runner writes one row per call after scoring. It adds `prompt`, `response`, `stop_reason` and `request_id` to the planned fields (PLAN.md contracts). Runs resume by skipping calls already logged. A run refuses to continue under a different model.

## D-021 Country selection rules and the 24 picks — confirm (refines D-009)
`src/select_countries.py` produces `configs/countries.yaml`. It also writes `data/familiarity/candidates.csv` (every candidate with its measures and the reason for any exclusion) and `analysis/figures/country_selection.png`.

- **Candidates:** the 195 names in `draw_test.py`. 55 are excluded, leaving 140:
  - 34 microstates (< 10,000 km², equal-area)
  - 14 with a disputed border that changes the outline. Natural Earth draws de facto lines (for example India's Kashmir), and a model may draw the claimed one. The list is `DISPUTED` in the script.
  - 5 archipelagos (> 5 parts kept)
  - 2 with a distant territory (> 1,000 km from the main part) and no hand-written scope. Hand-written scopes live in `configs/scope_overrides.yaml`.
- **Familiarity:** English Wikipedia pageviews over the **last 60 days** (Sep 20 – Nov 18, 2026, 59 days with data). Redirects are followed and disambiguation pages are rejected. The range is 89k (Togo) to 2.35M.
  - This **differs from D-009's 12 months.** The 12-month endpoint answered HTTP 429 (retry after 29 s) after two requests, which would make the fetch take over an hour. The MediaWiki API returns 60 days for 50 articles per request.
  - Limitation: a 60-day window picks up news spikes (Yemen and Saudi Arabia may be "popular" partly for that reason).
- **Complexity:** computed on the aligned reference, simplified at 0.01 √area so it doesn't depend on size. It is the mean percentile of two measures:
  - **roughness:** perimeter ÷ convex-hull perimeter − 1. This doesn't penalise elongated shapes, unlike 1 − isoperimetric quotient, which made Portugal look rough.
  - **concavity:** 1 − area ÷ hull area.
- **Cells:** median splits on both axes. In each cell, the 6 countries furthest from both medians are picked: the score is the smaller of the two distances, ranked from largest down.
- **Picks:**

| Cell | Countries |
|------|-----------|
| popular / simple | Poland, Saudi Arabia, Yemen, Albania, Sri Lanka, Ethiopia |
| popular / complex | United Kingdom, Japan, New Zealand, Mexico, Italy, Vietnam |
| niche / simple | Libya, Botswana, Lesotho, Niger, Burundi, Chad |
| niche / complex | Mozambique, Tajikistan, Costa Rica, Panama, Gambia, Republic of the Congo |

- **Scope sentence:** chosen automatically:
  - "the whole country" when Natural Earth has one part
  - "the main landmass only (leave out small islands)" when only one part survives the 1% rule
  - otherwise "the main landmasses only (leave out small islands)". This wording replaced "mainland …" in step 5, because Japan, the UK and New Zealand have no mainland.

  I checked all 24 references on a contact sheet.
- USA, France and Norway were not picked. Their hand-written scopes stay in `scope_overrides.yaml`.

## D-020 Evaluator details — settled (refines D-010, D-012)
- **What gets parsed:** every SVG shape element (`path`, `polygon`, `rect`, …), with transforms and the viewBox applied. Curves and arcs are sampled at 16 points per segment.
- **Repair:** each subpath becomes a polygon, which is repaired with `make_valid`. Pieces with zero area are dropped. A subpath inside another one fills it in (holes removed, D-012).
- **Boundary distances:** about 1000 evenly spaced points on each aligned boundary, measured to the other shape's boundary.
  - Hausdorff is the largest of these distances.
  - HD95 is the 95th percentile of the distances from both directions combined.
  - After alignment, the unit is √(area).
- **Check:** `pytest` runs 24 tests. They cover an exact score for a reference against itself, shifts and uniform scaling, and a reference → SVG → parse round trip. They also check that stretches, rotations and convex hulls score lower, and that unusable SVGs are marked invalid.

## D-019 Report a "blob floor" for each country — confirm (new)
An aligned disc already scores well on compact countries: IoU 0.76 against France and 0.61 against the United States, but 0.11 against Norway. Raw IoU therefore mixes knowledge with how compact the country is. For each country we report the disc's IoU and HD95 as a floor. We also report floor-normalised IoU, (IoU − IoU_disc) / (1 − IoU_disc), next to raw IoU.

Gains per round (ΔIoU) are paired within a country, so the floor does not affect them.

## D-018 How the scope rule selects reference parts — settled (refines D-006, D-007)
Each country spec in `configs/countries.yaml` can set:

- **`bbox`** (`[lon_min, lat_min, lon_max, lat_max]`): parts whose representative point lies inside are kept.
- **`min_part_frac`** (default 0.01): after projection, parts smaller than this share of the kept area are dropped.

The `scope` sentence in the prompt must describe the same parts. Countries that cross 180° have their western parts shifted by +360° before projection.

Checked on the three seed countries:

| Country | Parts in NE | Kept |
|---------|-------------|------|
| United States | 127 | 1 (the lower 48) |
| France | 10 | 2 (mainland, Corsica) |
| Norway | 32 | 2 (mainland, one large northern island) |

Name lookup tries ADMIN, then NAME, NAME_LONG, NAME_EN and FORMAL_EN. That resolves 193 of the 195 names in `draw_test.py`. "Cote d'Ivoire" and "Sao Tome and Principe" need `ne_name` (NE spells them with accents or as "Ivory Coast").

Known limitation: admin-0 polygons follow political borders through lakes. The US reference therefore has no Great Lakes indentation, while a drawing may show one. We keep the political outline and note it in the write-up.

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
