"""Step 6d: the per-round tables, on hand-made rows with known answers."""
import pytest

from results import round_table, validity_table


def d(cond, rnd, iou, valid=True, call_type="draw"):
    return {"country": "Poland", "sample": 0, "condition": cond, "round": rnd, "call_type": call_type,
            "iou": iou, "valid": valid, "judge_rating": None}


def j(cond, rnd, rating):
    return {**d(cond, rnd, None, None, "judge"), "judge_rating": rating}


ROWS = [d("C0", 0, 0.5), j("C0", 0, 5),
        d("C3", 1, 0.7), j("C3", 1, 4),
        d("C3", 2, 0.6), j("C3", 2, 9),
        d("C1", 1, 0.55, call_type="revise"), j("C1", 1, 6),
        d("C1", 2, 0.0, valid=False, call_type="revise")]


def test_round_table():
    t = round_table(ROWS, rounds=3)
    assert list(t.loc["C1 sees image + code", ["round 0", "round 1", "round 2"]]) == [0.5, 0.55, 0.0]
    assert list(t.loc["C3 resample, judge pick", ["round 0", "round 1", "round 2"]]) == [0.5, 0.5, 0.6]
    assert list(t.loc["C3 resample, best by IoU", ["round 0", "round 1", "round 2"]]) == [0.5, 0.7, 0.7]
    assert t.loc["C0 one-shot", "trials"] == 1
    assert "C2 sees code only" not in t.index


def test_validity_table():
    t = validity_table(ROWS, rounds=3)
    assert list(t.loc["C1 sees image + code", ["round 0", "round 1", "round 2"]]) == [1.0, 1.0, 0.0]
    assert not any(i.startswith("C3") for i in t.index)


def test_mean_over_trials():
    other = [{**r, "sample": 1, "iou": (r["iou"] if r["iou"] is None else 1.0)} for r in ROWS[:2]]
    t = round_table(ROWS[:2] + other, rounds=3)
    assert t.loc["C0 one-shot", "round 0"] == pytest.approx(0.75) and t.loc["C0 one-shot", "trials"] == 2
