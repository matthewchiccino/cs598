"""Step 6c: the judge probe and C3 resampling with judge selection, driven by a scripted fake client."""
import base64

import pytest

from conditions import draw, judge, revise, round0, select_best
from llm import LLM, Budget
from test_revise import RENDER, ScriptedClient, blocks, drawing, text_of

SECRET = "JUDGE-ONLY-TEXT"


def rating(n: int, verdict: str | None = None) -> str:
    return f"<reason>{SECRET}</reason><rating>{n}</rating>" + (f"<verdict>{verdict}</verdict>" if verdict else "")


@pytest.fixture(scope="module")
def poland():
    from groundtruth import load_countries, load_reference
    spec = next(c for c in load_countries() if c["name"] == "Poland")
    return spec, load_reference(spec)


def setup(replies):
    client = ScriptedClient(replies)
    return LLM({"name": "claude-haiku-5-5"}, client=client), Budget(1.0), client


def images(request) -> list[bytes]:
    return [base64.standard_b64decode(b["source"]["data"]) for b in blocks(request) if b["type"] == "image"]


def test_round0_judge_rates_one_image(poland, tmp_path):
    spec, ref = poland
    llm, budget, client = setup([drawing(ref, 1.3), rating(6)])
    r0 = round0(llm, budget, spec, 0, ref, "t", tmp_path)
    j = judge(llm, budget, spec, r0, None, "t", tmp_path, RENDER)
    assert (j["condition"], j["round"], j["call_type"]) == ("C0", 0, "judge")
    assert j["judge_rating"] == 6 and j["judge_verdict"] is None
    assert j["valid"] is None and j["iou"] is None and j["svg"] is None and j["cost_usd"] > 0
    assert j["prompt_id"].startswith("judge_v1:") and "[image: poland__C0__s0__r0.png]" in j["prompt"]
    assert images(client.requests[1]) == [(tmp_path / "png" / "poland__C0__s0__r0.png").read_bytes()]


def test_revision_judge_compares_with_previous(poland, tmp_path):
    spec, ref = poland
    llm, budget, client = setup([drawing(ref, 1.5), f"<critique>- wide</critique>{drawing(ref, 1.1)}",
                                 rating(8, "better")])
    r0 = round0(llm, budget, spec, 0, ref, "t", tmp_path)
    r1 = revise(llm, budget, "C1", spec, 0, ref, [r0], "t", tmp_path, RENDER)
    j = judge(llm, budget, spec, r1, r0, "t", tmp_path, RENDER)
    assert (j["condition"], j["round"], j["judge_rating"], j["judge_verdict"]) == ("C1", 1, 8, "better")
    png = tmp_path / "png"
    assert images(client.requests[2]) == [(png / "poland__C0__s0__r0.png").read_bytes(),
                                          (png / "poland__C1__s0__r1.png").read_bytes()]


def test_invalid_drawing_is_not_judged(poland, tmp_path):
    spec, ref = poland
    llm, budget, client = setup(["no svg", drawing(ref, 1.0), rating(9)])
    bad = round0(llm, budget, spec, 0, ref, "t", tmp_path)
    assert judge(llm, budget, spec, bad, None, "t", tmp_path, RENDER) is None
    assert len(client.requests) == 1
    # a revision after an invalid drawing is rated on its own, with no verdict
    good = {**round0(llm, budget, spec, 0, ref, "t", tmp_path), "condition": "C2", "round": 1}
    j = judge(llm, budget, spec, good, bad, "t", tmp_path, RENDER)
    assert len(images(client.requests[-1])) == 1 and "<verdict>" not in text_of(client.requests[-1])


def test_resamples_are_rated_alone(poland, tmp_path):
    spec, ref = poland
    llm, budget, _ = setup([drawing(ref, 1.0), drawing(ref, 1.0)])
    r0 = round0(llm, budget, spec, 0, ref, "t", tmp_path)
    r1 = draw(llm, budget, spec, 0, ref, "t", tmp_path, condition="C3", round_=1)
    with pytest.raises(ValueError):
        judge(llm, budget, spec, r1, r0, "t", tmp_path, RENDER)


def test_judge_never_reaches_the_drawing_calls(poland, tmp_path):
    spec, ref = poland
    replies = [drawing(ref, 1.5), rating(4)]
    for stretch in (1.3, 1.2, 1.1):
        replies += [f"<critique>- wide</critique>{drawing(ref, stretch)}", rating(5, "better")]
    llm, budget, client = setup(replies)
    rows = [round0(llm, budget, spec, 0, ref, "t", tmp_path)]
    judge(llm, budget, spec, rows[0], None, "t", tmp_path, RENDER)
    for _ in range(3):
        rows.append(revise(llm, budget, "C5", spec, 0, ref, rows, "t", tmp_path, RENDER))
        judge(llm, budget, spec, rows[-1], rows[-2], "t", tmp_path, RENDER)
    revise_requests = client.requests[2::2]
    assert len(revise_requests) == 3
    assert all(SECRET not in text_of(r) and "rating" not in text_of(r) for r in revise_requests)


def test_c3_trial(poland, tmp_path):
    """Round 0 plus three resamples, each rated; the judge picks round 1, the best by IoU is round 2."""
    spec, ref = poland
    llm, budget, client = setup([drawing(ref, 1.6), rating(3),
                                 drawing(ref, 1.3), rating(8),
                                 drawing(ref, 1.0), rating(7),
                                 "no svg"])
    drawings, judges = [round0(llm, budget, spec, 0, ref, "t", tmp_path)], []
    judges.append(judge(llm, budget, spec, drawings[0], None, "t", tmp_path, RENDER))
    for r in (1, 2, 3):
        drawings.append(draw(llm, budget, spec, 0, ref, "t", tmp_path, condition="C3", round_=r))
        j = judge(llm, budget, spec, drawings[-1], None, "t", tmp_path, RENDER)
        if j:
            judges.append(j)
    assert [(d["condition"], d["round"], d["call_type"]) for d in drawings] == \
        [("C0", 0, "draw"), ("C3", 1, "draw"), ("C3", 2, "draw"), ("C3", 3, "draw")]
    assert len(client.requests) == 7  # no judge call for the invalid round 3
    assert len({text_of(r) for r in client.requests[0::2]}) == 1  # every resample gets the round-0 prompt
    best = select_best(drawings, judges)
    assert best["judge_round"] == 1 and best["oracle_round"] == 2
    assert best["judge_iou"] == drawings[1]["iou"] and best["oracle_iou"] > 0.98


def row(round_, iou, rating_=None, sample=0):
    d = {"country": "Poland", "sample": sample, "round": round_, "iou": iou}
    j = {"country": "Poland", "sample": sample, "round": round_, "judge_rating": rating_}
    return d, j


@pytest.mark.parametrize("spec,judge_round,oracle_round", [
    ([(0, 0.5, 7), (1, 0.7, 7), (2, 0.7, 6)], 0, 1),      # ties go to the earliest round
    ([(0, 0.5, None), (1, 0.0, None), (2, 0.6, 4)], 2, 2),  # unrated drawings are not candidates
    ([(0, 0.5, None), (1, 0.6, None)], 0, 1),               # nothing rated: round 0
])
def test_select_best(spec, judge_round, oracle_round):
    pairs = [row(*s) for s in spec]
    best = select_best([d for d, _ in pairs], [j for _, j in pairs])
    assert (best["judge_round"], best["oracle_round"]) == (judge_round, oracle_round)


def test_select_best_refuses_mixed_trials():
    a, b = row(0, 0.5, 5), row(1, 0.6, 6, sample=1)
    with pytest.raises(ValueError):
        select_best([a[0], b[0]], [a[1], b[1]])
