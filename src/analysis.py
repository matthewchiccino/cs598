"""Step 8: figures and tables for RQ1-RQ4 from one run's call log (D-001, D-010, D-019, D-029).

Usage:
  python src/analysis.py --run main_claude-sonnet-5-5
Writes analysis/<run>/: fig_gain_rounds.png, fig_rounds.png, fig_gains.png, fig_cells.png, fig_judge.png and CSV tables,
and prints a short summary. Every number comes from runs/<run>/calls.jsonl, so rerunning regenerates all.

Uncertainty: 95% bootstrap intervals that resample countries (samples of one country are averaged
first), because the 3 samples of a country are not independent of each other.
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from conditions import REVISED
from groundtruth import ROOT, load_countries
from llm import RunLog
from plots import GRID, SURFACE, TEXT, TEXT_MUTED, _style
from results import LABELS, long_records

B = 2000                 # bootstrap resamples
SAME_TOL = 0.02          # |dIoU| below this counts as "same" when scoring judge verdicts (D-029)
CELLS = ["popular / simple", "popular / complex", "niche / simple", "niche / complex"]

# Categorical slots 1-4, validated for adjacent-pair CVD separation; C3's oracle reuses C3's hue, dashed.
COLORS = {"C1": "#2a78d6", "C2": "#eb6834", "C3_judge": "#1baf7a", "C3_oracle": "#1baf7a", "C5": "#eda100",
          "C0": TEXT_MUTED}
SHORT = {"C0": "C0 one-shot", "C1": "C1 image+code", "C2": "C2 code only", "C5": "C5 +IoU score",
         "C3_judge": "C3 resample (judge pick)", "C3_oracle": "C3 resample (oracle best)"}
CURVES = ["C1", "C2", "C5", "C3_judge", "C3_oracle"]


# ---------- data ----------

def records(rows: list[dict], rounds: int, specs: dict) -> pd.DataFrame:
    """long_records plus cell, disc floor and floor-normalised IoU (D-019)."""
    df = long_records(rows, rounds)
    meta = pd.DataFrame([{"country": n, "cell": f"{s['familiarity']} / {s['shape']}",
                          "disc_iou": s["disc_iou"]} for n, s in specs.items()])
    df = df.merge(meta, on="country", how="left")
    df["iou_norm"] = (df["iou"] - df["disc_iou"]) / (1 - df["disc_iou"])
    return df


def gains(df: pd.DataFrame, round_: int) -> pd.DataFrame:
    """One row per trial: each curve's IoU at round_ minus its round 0 (paired within trial)."""
    wide = df.pivot_table(index=["country", "sample", "cell"], columns=["condition", "round"], values="iou")
    out = pd.DataFrame(index=wide.index)
    for c in CURVES:
        if (c, round_) in wide.columns:
            out[c] = wide[(c, round_)] - wide[(c, 0)]
    return out.reset_index()


def gain_curves(df: pd.DataFrame, rounds: int) -> pd.DataFrame:
    """Mean paired gain over round 0 at each round, with country-bootstrap intervals."""
    recs = []
    for r in range(rounds + 1):
        g = gains(df, r)
        for c in CURVES:
            if c in g:
                m, lo, hi, n = bootstrap(g, c)
                recs.append({"condition": c, "round": r, "mean": m, "lo": lo, "hi": hi, "countries": n})
    return pd.DataFrame(recs)


def bootstrap(per_trial: pd.DataFrame, col: str, seed: int = 0) -> tuple[float, float, float, int]:
    """(mean, lo, hi, n_countries) of col; country means resampled with replacement."""
    by_country = per_trial.groupby("country")[col].mean().dropna().to_numpy()
    n = len(by_country)
    if n == 0:
        return (np.nan, np.nan, np.nan, 0)
    rng = np.random.default_rng(seed)
    means = by_country[rng.integers(0, n, size=(B, n))].mean(axis=1)
    return float(by_country.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), n


# ---------- RQ1 / RQ2: curves, gains, contrasts ----------

def round_curves(df: pd.DataFrame, value: str = "iou") -> pd.DataFrame:
    recs = []
    for (cond, r), g in df.groupby(["condition", "round"]):
        m, lo, hi, n = bootstrap(g, value)
        recs.append({"condition": cond, "round": r, "mean": m, "lo": lo, "hi": hi, "countries": n})
    return pd.DataFrame(recs)


def contrast_table(g: pd.DataFrame) -> pd.DataFrame:
    """Gain at the last round per curve, and the paired differences that answer RQ1 and RQ2."""
    pairs = [(c, None) for c in CURVES] + [("C1", "C3_judge"), ("C2", "C3_judge"), ("C1", "C2"), ("C5", "C1")]
    recs = []
    for a, b in pairs:
        if a not in g or (b and b not in g):
            continue
        col = g[a] - g[b] if b else g[a]
        m, lo, hi, n = bootstrap(g.assign(x=col), "x")
        name = f"gain {SHORT[a]}" if b is None else f"{SHORT[a]} minus {SHORT[b]}"
        recs.append({"comparison": name, "mean": m, "lo": lo, "hi": hi, "countries": n})
    return pd.DataFrame(recs)


def regression_table(df: pd.DataFrame, rounds: int) -> pd.DataFrame:
    """Share of revisions (round r vs r-1, same trial) that lowered IoU, per condition and round (D-010)."""
    recs = []
    for cond in [c for c in REVISED if c in set(df["condition"])]:
        d = df[df["condition"] == cond].pivot_table(index=["country", "sample"], columns="round", values="iou")
        for r in range(1, rounds + 1):
            if r in d and r - 1 in d:
                both = d[[r - 1, r]].dropna()
                recs.append({"condition": cond, "round": r, "revisions": len(both),
                             "lowered": float((both[r] < both[r - 1] - 1e-9).mean()),
                             "unchanged": float((abs(both[r] - both[r - 1]) <= 1e-9).mean())})
    return pd.DataFrame(recs)


# ---------- RQ3: familiarity x complexity ----------

def cell_table(df: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    recs = []
    r0 = df[(df["condition"] == "C0") & (df["round"] == 0)]
    for cell in CELLS:
        rec = {"cell": cell}
        for value in ("iou", "iou_norm"):
            m, lo, hi, n = bootstrap(r0[r0["cell"] == cell], value)
            rec.update({f"C0_{value}": m, f"C0_{value}_lo": lo, f"C0_{value}_hi": hi, "countries": n})
        for c in CURVES:
            if c in g:
                m, lo, hi, _ = bootstrap(g[g["cell"] == cell], c)
                rec.update({f"gain_{c}": m, f"gain_{c}_lo": lo, f"gain_{c}_hi": hi})
        recs.append(rec)
    return pd.DataFrame(recs)


# ---------- RQ4: judge calibration ----------

def judge_pairs(rows: list[dict]) -> pd.DataFrame:
    """One row per judged drawing: rating, verdict, the drawing's IoU and its true change from round r-1."""
    draws = {(r["condition"], r["country"], r["sample"], r["round"]): r for r in rows if r["call_type"] != "judge"}
    recs = []
    for j in rows:
        if j["call_type"] != "judge" or j["judge_rating"] is None:
            continue
        k = (j["condition"], j["country"], j["sample"], j["round"])
        d = draws.get(k)
        if d is None:
            continue
        rec = {"condition": j["condition"], "country": j["country"], "sample": j["sample"], "round": j["round"],
               "rating": j["judge_rating"], "verdict": j["judge_verdict"], "iou": d["iou"], "true_change": None}
        if j["judge_verdict"] and j["condition"] in REVISED and j["round"] >= 1:
            prev = draws.get(("C0" if j["round"] == 1 else j["condition"], j["country"], j["sample"], j["round"] - 1))
            if prev is not None and prev["valid"]:
                delta = d["iou"] - prev["iou"]
                rec["true_change"] = "same" if abs(delta) < SAME_TOL else ("better" if delta > 0 else "worse")
        recs.append(rec)
    return pd.DataFrame(recs, columns=["condition", "country", "sample", "round", "rating", "verdict", "iou",
                                       "true_change"])


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman rho as Pearson on average ranks (ties share a rank); avoids a scipy dependency."""
    return float(a.rank().corr(b.rank()))


def judge_summary(jp: pd.DataFrame) -> dict:
    """Spearman rating vs IoU, pooled and within country; verdict accuracy and confusion counts."""
    out = {"judged": len(jp)}
    if len(jp) >= 3:
        out["spearman_pooled"] = spearman(jp["rating"], jp["iou"])
        within = [spearman(g["rating"], g["iou"]) for _, g in jp.groupby("country")
                  if len(g) >= 3 and g["rating"].nunique() > 1 and g["iou"].nunique() > 1]
        out["spearman_within_country_mean"] = float(np.mean(within)) if within else None
        out["countries_within"] = len(within)
    v = jp.dropna(subset=["verdict", "true_change"])
    out["verdicts"] = len(v)
    if len(v):
        out["verdict_accuracy"] = float((v["verdict"] == v["true_change"]).mean())
        out["said_better_share"] = float((v["verdict"] == "better").mean())
        out["truly_better_share"] = float((v["true_change"] == "better").mean())
        out["confusion"] = pd.crosstab(v["verdict"], v["true_change"]).to_dict()
    return out


# ---------- figures ----------

def _save(fig, path: Path) -> Path:
    fig.patch.set_facecolor(SURFACE)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def fig_rounds(curves: pd.DataFrame, rounds: int, path: Path, value_label: str, title: str,
               bands: bool = True) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    _style(ax)
    ends = []
    for c in CURVES:
        d = curves[curves["condition"] == c].sort_values("round")
        if d.empty:
            continue
        dashed = c == "C3_oracle"
        if bands:
            ax.fill_between(d["round"], d["lo"], d["hi"], color=COLORS[c], alpha=0.08 if dashed else 0.12,
                            linewidth=0)
        ax.plot(d["round"], d["mean"], color=COLORS[c], linewidth=2, linestyle="--" if dashed else "-",
                marker="o", markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.5, label=SHORT[c])
        ends.append([d["mean"].iloc[-1], SHORT[c]])
    # Direct labels at the right end, nudged apart so they never overlap.
    ends.sort()
    span = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.045
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + span)
    for y, name in ends:
        ax.annotate(name, (rounds, y), xytext=(8, 0), textcoords="offset points", va="center", fontsize=8, color=TEXT)
    ax.set_xticks(range(rounds + 1))
    ax.set_xlim(-0.15, rounds + 1.1)
    ax.set_xlabel("Round (0 = shared one-shot drawing)", color=TEXT, fontsize=10)
    ax.set_ylabel(value_label, color=TEXT, fontsize=10)
    if bands:
        ax.axhline(0, color=TEXT_MUTED, linewidth=1)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left")
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(TEXT)
    return _save(fig, path)


def fig_gains(table: pd.DataFrame, path: Path) -> Path:
    """Forest plot: gains and paired contrasts with intervals; zero line marks 'no effect'."""
    t = table.iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(t) + 1.4), dpi=150)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.axvline(0, color=TEXT_MUTED, linewidth=1)
    for i, r in t.iterrows():
        ax.plot([r["lo"], r["hi"]], [i, i], color=TEXT, linewidth=2, solid_capstyle="round")
        ax.plot(r["mean"], i, "o", color=TEXT, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.annotate(f"{r['mean']:+.3f}", (r["hi"], i), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8, color=TEXT_MUTED)
    ax.set_yticks(range(len(t)))
    ax.set_yticklabels(t["comparison"], fontsize=8, color=TEXT)
    ax.set_xlabel("Change in IoU at the last round (paired within trial)", color=TEXT, fontsize=10)
    ax.set_title("Gains over round 0 and head-to-head contrasts", color=TEXT, fontsize=11, loc="left")
    return _save(fig, path)


def fig_cells(cells: pd.DataFrame, path: Path) -> Path:
    """Two panels: one-shot accuracy per cell (floor-normalised), and gain per cell per curve."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.6), dpi=150)
    for ax in (a, b):
        _style(ax)
        ax.grid(axis="x", visible=False)
    x = np.arange(len(CELLS))
    m, lo, hi = cells["C0_iou_norm"], cells["C0_iou_norm_lo"], cells["C0_iou_norm_hi"]
    a.bar(x, m, width=0.55, color=TEXT_MUTED, edgecolor=SURFACE, linewidth=2)
    a.errorbar(x, m, yerr=[m - lo, hi - m], fmt="none", ecolor=TEXT, elinewidth=1.2, capsize=3)
    a.axhline(0, color=TEXT_MUTED, linewidth=1)
    a.set_xticks(x)
    a.set_xticklabels([c.replace(" / ", "\n") for c in CELLS], fontsize=8, color=TEXT)
    a.set_ylabel("One-shot IoU above the disc floor (D-019)", color=TEXT, fontsize=9)
    a.set_title("How well it draws, by cell", color=TEXT, fontsize=11, loc="left")

    shown = [c for c in ["C1", "C2", "C5", "C3_judge"] if f"gain_{c}" in cells]
    w = 0.8 / max(1, len(shown))
    for i, c in enumerate(shown):
        xs = x - 0.4 + w * (i + 0.5)
        m, lo, hi = cells[f"gain_{c}"], cells[f"gain_{c}_lo"], cells[f"gain_{c}_hi"]
        b.bar(xs, m, width=w, color=COLORS[c], edgecolor=SURFACE, linewidth=2, label=SHORT[c])
        b.errorbar(xs, m, yerr=[m - lo, hi - m], fmt="none", ecolor=TEXT, elinewidth=1, capsize=2)
    b.axhline(0, color=TEXT_MUTED, linewidth=1)
    b.set_xticks(x)
    b.set_xticklabels([c.replace(" / ", "\n") for c in CELLS], fontsize=8, color=TEXT)
    b.set_ylabel("Gain in IoU, round 0 to last round", color=TEXT, fontsize=9)
    b.set_title("How much it improves, by cell", color=TEXT, fontsize=11, loc="left")
    leg = b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4, frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(TEXT)
    return _save(fig, path)


def fig_judge(jp: pd.DataFrame, summary: dict, path: Path) -> Path:
    """True IoU for each judge rating: does a higher self-rating mean a better drawing?"""
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150)
    _style(ax)
    ax.grid(axis="x", visible=False)
    rng = np.random.default_rng(0)
    ax.scatter(jp["rating"] + rng.uniform(-0.18, 0.18, len(jp)), jp["iou"], s=10, color=COLORS["C1"],
               alpha=0.35, linewidth=0)
    med = jp.groupby("rating")["iou"].median()
    ax.plot(med.index, med.values, color=TEXT, linewidth=2, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label="median IoU per rating")
    ax.set_xticks(range(1, 11))
    ax.set_xlim(0.5, 10.5)
    ax.set_xlabel("Judge's self-rating (1-10)", color=TEXT, fontsize=10)
    ax.set_ylabel("True IoU of the drawing", color=TEXT, fontsize=10)
    rho = summary.get("spearman_pooled")
    ax.set_title(f"Judge calibration: Spearman rho = {rho:.2f} over {len(jp)} drawings" if rho is not None
                 else "Judge calibration", color=TEXT, fontsize=11, loc="left")
    leg = ax.legend(loc="upper left", frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(TEXT)
    return _save(fig, path)


# ---------- CLI ----------

def analyse(rows: list[dict], rounds: int, specs: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df = records(rows, rounds, specs)
    g = gains(df, rounds)
    curves = round_curves(df)
    curves_norm = round_curves(df, "iou_norm")
    gcurves = gain_curves(df, rounds)
    contrasts = contrast_table(g)
    regress = regression_table(df, rounds)
    cells = cell_table(df, g)
    jp = judge_pairs(rows)
    js = judge_summary(jp)

    curves.to_csv(out / "rounds_iou.csv", index=False)
    curves_norm.to_csv(out / "rounds_iou_norm.csv", index=False)
    contrasts.to_csv(out / "contrasts.csv", index=False)
    regress.to_csv(out / "regressions.csv", index=False)
    cells.to_csv(out / "cells.csv", index=False)
    jp.to_csv(out / "judge_pairs.csv", index=False)
    (out / "judge_summary.json").write_text(json.dumps(js, indent=2, default=str), encoding="utf-8")

    gcurves.to_csv(out / "rounds_gain.csv", index=False)
    fig_rounds(gcurves, rounds, out / "fig_gain_rounds.png", "Gain in IoU over round 0",
               "Gain over the one-shot drawing by round (paired, 95% CI over countries)")
    fig_rounds(curves, rounds, out / "fig_rounds.png", "Mean IoU",
               "Mean IoU by round (countries differ widely; see the gain chart for intervals)", bands=False)
    fig_rounds(curves_norm, rounds, out / "fig_rounds_norm.png", "Floor-normalised IoU",
               "Floor-normalised IoU by round (D-019)", bands=False)
    if not contrasts.empty:
        fig_gains(contrasts, out / "fig_gains.png")
    fig_cells(cells, out / "fig_cells.png")
    if len(jp):
        fig_judge(jp, js, out / "fig_judge.png")
    return {"contrasts": contrasts, "regressions": regress, "cells": cells, "judge": js}


def main(argv=None):
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--runs-dir", help="directory holding <run>/calls.jsonl (default: runs_dir in the config)")
    ap.add_argument("--out", help="output directory (default: analysis/<run>)")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    run_dir = Path(args.runs_dir or ROOT / cfg["runs_dir"]) / args.run
    if not (run_dir / "calls.jsonl").exists():
        raise SystemExit(f"No log at {run_dir / 'calls.jsonl'}")
    rounds = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["experiment"]["rounds"]
    specs = {c["name"]: c for c in load_countries()}
    out = Path(args.out) if args.out else ROOT / "analysis" / args.run
    res = analyse(RunLog(run_dir / "calls.jsonl").rows(), rounds, specs, out)

    fmt = {"float_format": "{:+.3f}".format, "index": False}
    print("\nGains at the last round and contrasts (95% CI over countries)\n" + res["contrasts"].to_string(**fmt))
    print("\nShare of revisions that lowered IoU\n" + res["regressions"].to_string(index=False, float_format="{:.2f}".format))
    j = res["judge"]
    print(f"\nJudge: {j['judged']} ratings, Spearman pooled {j.get('spearman_pooled', float('nan')):.2f}, "
          f"within country {j.get('spearman_within_country_mean') or float('nan'):.2f}; "
          f"verdict accuracy {j.get('verdict_accuracy', float('nan')):.2f} over {j['verdicts']} verdicts")
    print(f"\nWrote figures and tables to {out}")


if __name__ == "__main__":
    main()
