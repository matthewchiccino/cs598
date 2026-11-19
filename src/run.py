"""Run experiment conditions and log one JSONL row per API call. Resumable: finished calls are skipped.

Usage:
  python src/run.py --run pilot_c0 --countries Poland Japan Lesotho Gambia Italy --samples 2
  python src/run.py --run pilot_c0 --dry-run      # list the calls that would be made, spend nothing
  python src/run.py --model claude-opus-5-5 --thinking --countries Italy --samples 1
The run name defaults to <run_name>_<model>, so each model gets its own log.
Writes runs/<run>/calls.jsonl, runs/<run>/config.json, runs/<run>/svg/ and runs/<run>/round0_gallery.png.
"""
import argparse
import json
from pathlib import Path

import yaml

from conditions import round0
from draw_test import load_env
from groundtruth import ROOT, load_countries, load_reference
from llm import LLM, PRICES, Budget, BudgetExceeded, RunLog, thinking_off


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


def main(argv=None, client=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "configs" / "default.yaml"))
    ap.add_argument("--run", help="run name (default: <run_name>_<model>)")
    ap.add_argument("--model", help="model ID, overriding model.name in the config")
    ap.add_argument("--thinking", action="store_true",
                    help="leave thinking on (required for models that cannot turn it off, e.g. claude-opus-5-5)")
    ap.add_argument("--countries", nargs="*", help="country names (default: all in countries.yaml)")
    ap.add_argument("--samples", type=int, help="samples per country (default: from the config)")
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
    run = args.run or f"{cfg['run_name']}_{model}"
    samples = args.samples or cfg["experiment"]["samples"]
    countries = select_countries(args.countries)
    run_dir = ROOT / cfg["runs_dir"] / run
    log = RunLog(run_dir / "calls.jsonl")

    done = {(r["condition"], r["country"], r["sample"], r["round"], r["call_type"]) for r in log.rows()}
    todo = [(c, s) for c in countries for s in range(samples) if ("C0", c["name"], s, 0, "draw") not in done]
    print(f"run '{run}': {len(todo)} calls to make, {len(done)} already logged, model {model} "
          f"(thinking {'on' if cfg['model']['thinking'] else 'off'}), "
          f"spent so far ${log.spent():.4f} of ${cfg['budget']['max_usd']:.2f}")
    if args.dry_run:
        for c, s in todo:
            print(f"  C0 {c['name']} sample {s}")
        return

    snapshot_config(run_dir, cfg)
    if client is None:
        load_env()
    llm = LLM(cfg["model"], client=client)
    budget = Budget(cfg["budget"]["max_usd"], log.spent())
    refs = {}
    try:
        for c, s in todo:
            ref = refs.setdefault(c["name"], load_reference(c))
            row = round0(llm, budget, c, s, ref, run, run_dir)
            log.append(row)
            iou = f"{row['iou']:.3f}" if row["valid"] else "invalid"
            print(f"  C0 {c['name']:22s} s{s}  IoU {iou:>7s}  {row['output_tokens']:5d} out tok  ${row['cost_usd']:.4f}")
    except BudgetExceeded as e:
        print(f"Stopped: budget cap reached ({e}). Raise budget.max_usd to continue; finished calls are kept.")

    from plots import plot_round0_gallery
    rows = [r for r in log.rows() if r["condition"] == "C0"]
    if rows:
        path = plot_round0_gallery(rows, {c["name"]: c for c in load_countries()}, run_dir / "round0_gallery.png")
        print(f"spent ${log.spent():.4f}; gallery: {path}")


if __name__ == "__main__":
    main()
