"""Step 8: analysis on hand-made rows with known answers."""
import pandas as pd
import pytest

from analysis import (analyse, bootstrap, contrast_table, gains, judge_pairs, judge_summary, records,
                      regression_table, spearman)

SPECS = {"Poland": {"familiarity": "popular", "shape": "simple", "disc_iou": 0.5},
         "Chad": {"familiarity": "niche", "shape": "simple", "disc_iou": 0.6}}


def d(cond, rnd, iou, country="Poland", sample=0, valid=True, call_type="draw"):
    return {"country": country, "sample": sample, "condition": cond, "round": rnd, "call_type": call_type,
            "iou": iou, "valid": valid, "judge_rating": None, "judge_verdict": None}


def j(cond, rnd, rating, verdict=None, country="Poland", sample=0):
    return {**d(cond, rnd, None, country, sample, None, "judge"), "judge_rating": rating, "judge_verdict": verdict}


def trial(country, sample, r0, c1, c3):
    """C0 round 0, C1 rounds 1-2 (revise), C3 rounds 1-2 (draw)."""
    return ([d("C0", 0, r0, country, sample)]
            + [d("C1", r, v, country, sample, call_type="revise") for r, v in enumerate(c1, 1)]
            + [d("C3", r, v, country, sample) for r, v in enumerate(c3, 1)])


ROWS = trial("Poland", 0, 0.5, [0.6, 0.7], [0.4, 0.55]) + trial("Chad", 0, 0.8, [0.7, 0.8], [0.9, 0.6])


def test_floor_normalised_iou():
    df = records(ROWS, 2, SPECS)
    r0 = df[(df["condition"] == "C0") & (df["country"] == "Poland")].iloc[0]
    assert r0["iou_norm"] == pytest.approx(0.0)          # (0.5 - 0.5) / (1 - 0.5)
    chad = df[(df["condition"] == "C0") & (df["country"] == "Chad")].iloc[0]
    assert chad["iou_norm"] == pytest.approx(0.5)        # (0.8 - 0.6) / 0.4
    assert chad["cell"] == "niche / simple"


def test_paired_gains_and_contrast():
    g = gains(records(ROWS, 2, SPECS), 2).set_index("country")
    assert g.loc["Poland", "C1"] == pytest.approx(0.2) and g.loc["Chad", "C1"] == pytest.approx(0.0)
    # C3 oracle at round 2 is the best of rounds 0..2: Poland 0.55, Chad 0.9.
    assert g.loc["Poland", "C3_oracle"] == pytest.approx(0.05) and g.loc["Chad", "C3_oracle"] == pytest.approx(0.1)
    t = contrast_table(g.reset_index()).set_index("comparison")
    assert t.loc["gain C1 image+code", "mean"] == pytest.approx(0.1)
    assert t.loc["gain C1 image+code", "countries"] == 2


def test_bootstrap_averages_samples_within_country_first():
    df = pd.DataFrame({"country": ["A", "A", "A", "B"], "x": [1.0, 1.0, 1.0, 0.0]})
    m, lo, hi, n = bootstrap(df, "x")
    assert (m, n) == (0.5, 2)                            # not 0.75: A's three samples count once
    assert 0.0 <= lo <= m <= hi <= 1.0
    single = bootstrap(df[df["country"] == "A"], "x")
    assert single[:3] == (1.0, 1.0, 1.0)


def test_regression_rate():
    t = regression_table(records(ROWS, 2, SPECS), 2).set_index("round")
    assert t.loc[1, "lowered"] == pytest.approx(0.5)     # Chad 0.8 -> 0.7
    assert t.loc[2, "lowered"] == pytest.approx(0.0)


def test_judge_verdicts_against_true_change():
    rows = ROWS + [j("C1", 1, 6, "better"), j("C1", 2, 7, "better"),
                   j("C1", 1, 5, "better", "Chad"), j("C1", 2, 9, "same", "Chad")]
    jp = judge_pairs(rows).set_index(["country", "round"])
    assert jp.loc[("Poland", 1), "true_change"] == "better"   # 0.5 -> 0.6
    assert jp.loc[("Chad", 1), "true_change"] == "worse"      # 0.8 -> 0.7
    assert jp.loc[("Chad", 2), "true_change"] == "better"     # 0.7 -> 0.8
    s = judge_summary(jp.reset_index())
    assert s["verdicts"] == 4 and s["verdict_accuracy"] == pytest.approx(0.5)


def test_same_needs_change_below_tolerance():
    rows = [d("C0", 0, 0.5), d("C1", 1, 0.51, call_type="revise"), j("C1", 1, 5, "same")]
    assert judge_pairs(rows).iloc[0]["true_change"] == "same"


def test_spearman_ties_and_monotone():
    assert spearman(pd.Series([1, 2, 3, 4]), pd.Series([0.1, 0.2, 0.5, 0.9])) == pytest.approx(1.0)
    assert spearman(pd.Series([1, 2, 3]), pd.Series([0.9, 0.5, 0.1])) == pytest.approx(-1.0)


def test_analyse_writes_every_output(tmp_path):
    rows = ROWS + [j("C0", 0, 5), j("C1", 1, 6, "better"), j("C0", 0, 8, country="Chad"),
                   j("C1", 1, 4, "worse", "Chad")]
    analyse(rows, 2, SPECS, tmp_path)
    for name in ["fig_gain_rounds.png", "fig_rounds.png", "fig_gains.png", "fig_cells.png", "fig_judge.png",
                 "contrasts.csv", "cells.csv", "regressions.csv", "judge_summary.json", "rounds_gain.csv"]:
        assert (tmp_path / name).exists(), name
