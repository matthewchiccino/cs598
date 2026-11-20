"""Per-round tables from a run's call log: mean IoU and validity per condition and round.

Usage:
  python src/results.py --run pilot_claude-haiku-5-5
Round 0 is the shared C0 drawing in every row. C3 at round k is the pick among rounds 0..k (D-026).
An invalid drawing counts as IoU 0.
"""
import argparse
import json
from collections import defaultdict

import pandas as pd

from conditions import REVISED, select_best
from groundtruth import ROOT
from llm import RunLog

LABELS = {
    "C0": "C0 one-shot",
    "C1": "C1 sees image + code",
    "C2": "C2 sees code only",
    "C5": "C5 sees image + code + IoU",
    "C3_judge": "C3 resample, judge pick",
    "C3_oracle": "C3 resample, best by IoU",
}


def trials(rows: list[dict]) -> dict:
    """{(country, sample): {"draws": {(condition, round): row}, "judges": {(condition, round): row}}}"""
    out = defaultdict(lambda: {"draws": {}, "judges": {}})
    for r in rows:
        kind = "judges" if r["call_type"] == "judge" else "draws"
        out[(r["country"], r["sample"])][kind][(r["condition"], r["round"])] = r
    return out


def long_records(rows: list[dict], rounds: int) -> pd.DataFrame:
    """One record per (trial, condition, round) that has a drawing: country, sample, condition, round, iou, valid."""
    recs = []
    for (country, sample), t in trials(rows).items():
        draws, judges = t["draws"], t["judges"]
        r0 = draws.get(("C0", 0))
        if r0 is None:
            continue
        base = {"country": country, "sample": sample}
        recs.append({**base, "condition": "C0", "round": 0, "iou": r0["iou"], "valid": r0["valid"]})
        for cond in REVISED:
            if not any(c == cond for c, _ in draws):
                continue
            for k in range(rounds + 1):
                row = r0 if k == 0 else draws.get((cond, k))
                if row is not None:
                    recs.append({**base, "condition": cond, "round": k, "iou": row["iou"], "valid": row["valid"]})
        chain = [r0]
        for k in range(1, rounds + 1):
            if ("C3", k) not in draws:
                break
            chain.append(draws[("C3", k)])
        if len(chain) > 1:
            for k in range(len(chain)):
                rated = [j for j in ([judges.get(("C0", 0))] + [judges.get(("C3", i)) for i in range(1, k + 1)])
                         if j is not None]
                best = select_best(chain[:k + 1], rated)
                recs.append({**base, "condition": "C3_judge", "round": k, "iou": best["judge_iou"], "valid": None})
                recs.append({**base, "condition": "C3_oracle", "round": k, "iou": best["oracle_iou"], "valid": None})
    return pd.DataFrame(recs, columns=["country", "sample", "condition", "round", "iou", "valid"])


def _pivot(df: pd.DataFrame, value: str) -> pd.DataFrame:
    order = [c for c in LABELS if c in set(df["condition"])]
    table = df.pivot_table(index="condition", columns="round", values=value, aggfunc="mean").reindex(order)
    table.insert(0, "trials", df[df["round"] == 0].groupby("condition").size().reindex(order))
    table.index = [LABELS[c] for c in order]
    table.columns = ["trials"] + [f"round {c}" for c in table.columns[1:]]
    return table


def round_table(rows: list[dict], rounds: int) -> pd.DataFrame:
    """Mean IoU per condition (rows) and round (columns), with the number of trials."""
    return _pivot(long_records(rows, rounds), "iou")


def validity_table(rows: list[dict], rounds: int) -> pd.DataFrame:
    """Share of drawings that parsed to a shape, per condition and round (C3 picks excluded)."""
    df = long_records(rows, rounds)
    df = df[df["valid"].notna()].assign(valid=lambda d: d["valid"].astype(float))
    return _pivot(df, "valid")


def print_tables(rows: list[dict], rounds: int):
    if not any(r["call_type"] != "judge" for r in rows):
        print("no drawings logged yet")
        return
    fmt = {"float_format": "{:.3f}".format, "na_rep": "-"}
    print("\nMean IoU (invalid = 0)\n" + round_table(rows, rounds).to_string(**fmt))
    print("\nValid drawings (share)\n" + validity_table(rows, rounds).to_string(**fmt))


def main(argv=None):
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    run_dir = ROOT / cfg["runs_dir"] / args.run
    if not (run_dir / "calls.jsonl").exists():
        raise SystemExit(f"No log at {run_dir / 'calls.jsonl'}")
    run_cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    print_tables(RunLog(run_dir / "calls.jsonl").rows(), run_cfg["experiment"]["rounds"])


if __name__ == "__main__":
    main()
