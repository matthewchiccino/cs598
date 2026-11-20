"""Run experiment conditions and log one JSONL row per API call. Resumable: finished calls are skipped.

Usage:
  python src/run.py --countries Poland Japan Lesotho Gambia Italy --samples 2
  python src/run.py --dry-run                     # calls still to make and a rough cost, spend nothing
  python src/run.py --conditions C0 --samples 2   # round 0 (and its judge call) only
  python src/run.py --model claude-opus-5-5 --thinking --countries Italy --samples 1
The run name defaults to <run_name>_<model>, so each model gets its own log.

Each trial (country x sample) runs in this order: the shared round-0 drawing and its judge call, then
for every revision condition (C1, C2, C5) rounds 1..R of revise + judge, then C3 rounds 1..R of
draw + judge. An invalid drawing gets no judge call (D-026).
Writes runs/<run>/calls.jsonl, config.json, svg/, png/ and round0_gallery.png, then prints the
per-round tables (src/results.py).
"""
import argparse
import json
from pathlib import Path

import yaml

from conditions import REVISED, draw, judge, revise
from draw_test import load_env
from groundtruth import ROOT, load_countries, load_reference
from llm import LLM, PRICES, Budget, BudgetExceeded, RunLog, cost_usd, thinking_off

CONDITIONS = ("C0", "C1", "C2", "C3", "C5")

# Rough (input, output) tokens per call until a log has real numbers; the pilot replaces these.
GUESS_TOKENS = {"draw": (250, 3000), "revise": (4000, 3200), "judge": (900, 80)}


def key(row: dict) -> tuple:
    return row["condition"], row["country"], row["sample"], row["round"], row["call_type"]


def plan(countries: list[dict], samples: int, conditions: list[str], rounds: int, judged: bool) -> list[tuple]:
    """Every call key of the experiment, in run order; judge calls for invalid drawings are skipped later."""
    keys = []
    for c in countries:
        for s in range(samples):
            def add(cond, r, call_type):
                keys.append((cond, c["name"], s, r, call_type))
                if judged:
                    keys.append((cond, c["name"], s, r, "judge"))
            add("C0", 0, "draw")
            for cond in conditions:
                if cond in REVISED:
                    for r in range(1, rounds + 1):
                        add(cond, r, "revise")
            if "C3" in conditions:
                for r in range(1, rounds + 1):
                    add("C3", r, "draw")
    return keys


def estimate_usd(model: str, todo: list[tuple], logged: list[dict]) -> tuple[float, str]:
    """Cost of the calls still to make, from mean tokens per call type in the log, else GUESS_TOKENS."""
    means, source = {}, "log"
    for call_type, guess in GUESS_TOKENS.items():
        seen = [r for r in logged if r["call_type"] == call_type]
        if seen:
            means[call_type] = (sum(r["input_tokens"] for r in seen) / len(seen),
                                sum(r["output_tokens"] for r in seen) / len(seen))
        else:
            means[call_type], source = guess, "guessed tokens (no pilot yet)"
    return sum(cost_usd(model, *means[k[4]]) for k in todo), source


def select_countries(names: list[str] | None) -> list[dict]:
    specs = load_countries()
    if not names:
        return specs
    by_name = {c["name"].lower(): c for c in specs}
    missing = [n for n in names if n.lower() not in by_name]
    if missing:
        raise SystemExit(f"Not in configs/countries.yaml: {', '.join(missing)}")
    return [by_name[n.lower()] for n in names]


def snapshot_config(run_dir: Path, cfg: dict):
    """Save the config on first use; refuse to mix models or settings within one run."""
    path = run_dir / "config.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old["model"] != cfg["model"]:
            raise SystemExit(f"{path} was run with {old['model']}; use a new --run name")
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class Runner:
    """Makes each call once: a key already in the log returns the logged row."""

    def __init__(self, llm, budget, log: RunLog, run: str, run_dir: Path, render_cfg: dict):
        self.llm, self.budget, self.log = llm, budget, log
        self.run, self.run_dir, self.render_cfg = run, run_dir, render_cfg
        self.logged = {key(r): r for r in log.rows()}

    def step(self, k: tuple, make):
        if k in self.logged:
            return self.logged[k]
        row = make()
        if row is not None:
            self.log.append(row)
            self.logged[k] = row
            print(f"  {k[0]} {k[1]:22s} s{k[2]} r{k[3]} {k[4]:6s}  {describe(row)}")
        return row

    def trial(self, country: dict, sample: int, ref, conditions: list[str], rounds: int, judged: bool):
        name, args = country["name"], (self.run, self.run_dir)
        llm, budget, render = self.llm, self.budget, self.render_cfg

        def rate(drawing, previous=None):
            if judged and drawing is not None:
                self.step(key({**drawing, "call_type": "judge"}),
                          lambda: judge(llm, budget, country, drawing, previous, *args, render))

        r0 = self.step(("C0", name, sample, 0, "draw"), lambda: draw(llm, budget, country, sample, ref, *args))
        rate(r0)
        for cond in [c for c in conditions if c in REVISED]:
            history = [r0]
            for r in range(1, rounds + 1):
                row = self.step((cond, name, sample, r, "revise"),
                                lambda: revise(llm, budget, cond, country, sample, ref, history, *args, render))
                rate(row, history[-1])
                history.append(row)
        if "C3" in conditions:
            for r in range(1, rounds + 1):
                rate(self.step(("C3", name, sample, r, "draw"),
                               lambda: draw(llm, budget, country, sample, ref, *args, condition="C3", round_=r)))


def describe(row: dict) -> str:
    if row["call_type"] == "judge":
        what = f"rating {row['judge_rating']}" + (f", {row['judge_verdict']}" if row["judge_verdict"] else "")
    else:
        what = f"IoU {row['iou']:.3f}" if row["valid"] else "invalid"
    return f"{what:22s} {row['output_tokens']:5d} out tok  ${row['cost_usd']:.4f}"


def main(argv=None, client=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "configs" / "default.yaml"))
    ap.add_argument("--run", help="run name (default: <run_name>_<model>)")
    ap.add_argument("--model", help="model ID, overriding model.name in the config")
    ap.add_argument("--thinking", action="store_true",
                    help="leave thinking on (required for models that cannot turn it off, e.g. claude-opus-5-5)")
    ap.add_argument("--countries", nargs="*", help="country names (default: all in countries.yaml)")
    ap.add_argument("--samples", type=int, help="samples per country (default: from the config)")
    ap.add_argument("--conditions", nargs="*", choices=CONDITIONS,
                    help="conditions to run (default: from the config); round 0 always runs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.model:
        cfg["model"]["name"] = args.model
    if args.thinking:
        cfg["model"]["thinking"] = True
    model = cfg["model"]["name"]
    if model not in PRICES:
        raise SystemExit(f"No price for {model}; add it to PRICES in src/llm.py ({', '.join(PRICES)})")
    if not cfg["model"]["thinking"]:
        try:
            thinking_off(model)
        except ValueError as e:
            raise SystemExit(f"{e}. Add --thinking; its results are not comparable with thinking-off runs (D-023).")
    exp = cfg["experiment"]
    conditions = args.conditions if args.conditions is not None else exp["conditions"]
    rounds, judged = exp["rounds"], exp["judge"]
    run = args.run or f"{cfg['run_name']}_{model}"
    samples = args.samples or exp["samples"]
    countries = select_countries(args.countries)
    run_dir = ROOT / cfg["runs_dir"] / run
    log = RunLog(run_dir / "calls.jsonl")

    rows = log.rows()
    logged = {key(r) for r in rows}
    todo = [k for k in plan(countries, samples, conditions, rounds, judged) if k not in logged]
    usd, source = estimate_usd(model, todo, rows)
    print(f"run '{run}': model {model} (thinking {'on' if cfg['model']['thinking'] else 'off'}), "
          f"conditions {' '.join(conditions)}, {rounds} rounds, judge {'on' if judged else 'off'}")
    print(f"  {len(todo)} calls to make (at most; invalid drawings skip their judge call), {len(logged)} logged")
    print(f"  estimated ${usd:.2f} more from {source}; spent ${log.spent():.4f} of ${cfg['budget']['max_usd']:.2f}")
    if args.dry_run:
        counts = {}
        for k in todo:
            counts[(k[0], k[4])] = counts.get((k[0], k[4]), 0) + 1
        for (cond, call_type), n in sorted(counts.items()):
            print(f"    {cond} {call_type:6s} {n:5d}")
        return

    snapshot_config(run_dir, cfg)
    if client is None:
        load_env()
    runner = Runner(LLM(cfg["model"], client=client), Budget(cfg["budget"]["max_usd"], log.spent()),
                    log, run, run_dir, cfg["render"])
    try:
        for c in countries:
            ref = load_reference(c)
            for s in range(samples):
                runner.trial(c, s, ref, conditions, rounds, judged)
    except BudgetExceeded as e:
        print(f"Stopped: budget cap reached ({e}). Raise budget.max_usd to continue; finished calls are kept.")

    from plots import plot_round0_gallery
    from results import print_tables
    rows = log.rows()
    drawings = [r for r in rows if r["condition"] == "C0" and r["call_type"] == "draw"]
    if drawings:
        path = plot_round0_gallery(drawings, {c["name"]: c for c in load_countries()}, run_dir / "round0_gallery.png")
        print(f"spent ${log.spent():.4f}; gallery: {path}")
    print_tables(rows, rounds)


if __name__ == "__main__":
    main()
