"""Step 5 checks without spending money: a fake client stands in for the Claude API."""
import json
from types import SimpleNamespace

import pytest
import yaml

import run as run_module
from geometry import geometry_to_svg
from groundtruth import ROOT, load_countries, load_reference
from llm import LLM, Budget, BudgetExceeded, cost_usd, thinking_off
from shapely import affinity


def request_text(kw) -> str:
    content = kw["messages"][0]["content"]
    return content if isinstance(content, str) else "\n".join(b["text"] for b in content if b["type"] == "text")


class FakeClient:
    """Draw and revise requests get the reference outline stretched by `stretch`; judge requests a rating.

    text: a fixed reply for every request.
    """

    def __init__(self, stretch: float = 1.0, text: str | None = None):
        self.stretch, self.text, self.requests = stretch, text, []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        prompt = request_text(kw)
        name = next(c["name"] for c in load_countries() if f"outline of {c['name']} " in prompt)
        spec = next(c for c in load_countries() if c["name"] == name)
        geom = affinity.scale(load_reference(spec), self.stretch, 1.0)
        if self.text is not None:
            text = self.text
        elif "<rating>" in prompt:
            text = "<reason>fine</reason><rating>7</rating>" + ("<verdict>same</verdict>" if "<verdict>" in prompt else "")
        elif "<critique>" in prompt:
            text = f"<critique>- looks right</critique>\n{geometry_to_svg(geom)}"
        else:
            text = f"Here you go:\n{geometry_to_svg(geom)}"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=200, output_tokens=3000), _request_id="req_test")


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    cfg["runs_dir"] = str(tmp_path / "runs")
    cfg["model"]["name"] = "claude-haiku-5-5"  # the costs and budget caps below are worked out on Haiku prices
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(run_module, "ROOT", tmp_path)
    return path, cfg


def test_thinking_off_per_model():
    assert thinking_off("claude-haiku-5-5") == {"type": "disabled"}
    assert thinking_off("claude-sonnet-5-5") == {"type": "between_tools"}
    with pytest.raises(ValueError):
        thinking_off("claude-opus-5-5")


def test_cost():
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert cost_usd("claude-sonnet-5-5", 200, 3000) == pytest.approx(0.0304)


def test_request_has_no_sampling_params():
    kw = LLM({"name": "claude-haiku-5-5", "max_tokens": 16000, "effort": "high"}, client=object()).request_kwargs("hi")
    assert kw["thinking"] == {"type": "disabled"} and kw["output_config"] == {"effort": "high"}
    assert not {"temperature", "top_p", "top_k"} & kw.keys()


def test_budget_blocks_before_spending():
    b = Budget(0.01, spent=0.01)
    with pytest.raises(BudgetExceeded):
        b.check()


def read_log(tmp_path, run) -> list[dict]:
    log = tmp_path / "runs" / run / "calls.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_round0_only_logs_scores_and_resumes(cfg_file, tmp_path):
    path, cfg = cfg_file
    fake = FakeClient()
    args = ["--config", str(path), "--run", "t", "--countries", "Poland", "Japan", "--samples", "2",
            "--conditions", "C0"]
    run_module.main(args, client=fake)
    rows = read_log(tmp_path, "t")
    draws = [r for r in rows if r["call_type"] == "draw"]
    assert len(rows) == 8 and len(fake.requests) == 8 and len(draws) == 4  # 4 drawings, 4 judge calls
    assert all(r["valid"] and r["iou"] > 0.99 for r in draws)
    assert all(r["prompt_id"].startswith("draw_v1:") and r["cost_usd"] > 0 for r in draws)
    assert (tmp_path / "runs" / "t" / "round0_gallery.png").exists()

    run_module.main(args, client=fake)  # second run makes no new calls
    assert len(fake.requests) == 8


def test_distorted_and_invalid_replies_are_scored(cfg_file, tmp_path):
    path, _ = cfg_file
    one = ["--config", str(path), "--countries", "Poland", "--samples", "1", "--conditions", "C0"]
    run_module.main(one + ["--run", "d"], client=FakeClient(stretch=1.5))
    run_module.main(one + ["--run", "x"], client=FakeClient(text="I cannot draw that."))
    d = read_log(tmp_path, "d")[0]
    x, *rest = read_log(tmp_path, "x")
    assert rest == []  # no judge call for an invalid drawing
    assert d["valid"] and d["iou"] < 0.9
    assert not x["valid"] and x["iou"] == 0 and x["svg"] is None


def test_model_option_overrides_config(cfg_file, tmp_path):
    path, _ = cfg_file
    fake = FakeClient()
    run_module.main(["--config", str(path), "--model", "claude-sonnet-5-5", "--countries", "Poland", "--samples", "1",
                     "--conditions", "C0"], client=fake)
    run_dir = tmp_path / "runs" / "main_claude-sonnet-5-5"  # default run name is <run_name>_<model>
    row = read_log(tmp_path, "main_claude-sonnet-5-5")[0]
    assert row["model"] == "claude-sonnet-5-5"
    assert fake.requests[0]["model"] == "claude-sonnet-5-5"
    assert fake.requests[0]["thinking"] == {"type": "between_tools"}
    assert json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["model"]["name"] == "claude-sonnet-5-5"


def test_opus_needs_thinking_flag(cfg_file, tmp_path):
    path, _ = cfg_file
    base = ["--config", str(path), "--model", "claude-opus-5-5", "--countries", "Poland", "--samples", "1",
            "--conditions", "C0"]
    with pytest.raises(SystemExit, match="--thinking"):
        run_module.main(base, client=FakeClient())
    fake = FakeClient()
    run_module.main(base + ["--thinking"], client=fake)
    assert "thinking" not in fake.requests[0]  # omitted = adaptive thinking
    row = read_log(tmp_path, "main_claude-opus-5-5")[0]
    assert row["cost_usd"] == pytest.approx(cost_usd("claude-opus-5-5", 200, 3000))


def test_unknown_model_is_rejected(cfg_file):
    path, _ = cfg_file
    with pytest.raises(SystemExit, match="No price"):
        run_module.main(["--config", str(path), "--model", "claude-made-up", "--dry-run"], client=FakeClient())


def test_same_run_refuses_a_second_model(cfg_file):
    path, _ = cfg_file
    args = ["--config", str(path), "--run", "same", "--countries", "Poland", "--samples", "1", "--conditions", "C0"]
    run_module.main(args, client=FakeClient())
    with pytest.raises(SystemExit, match="new --run name"):
        run_module.main(args + ["--samples", "2", "--model", "claude-sonnet-5-5"], client=FakeClient())


def test_budget_cap_stops_run(cfg_file, tmp_path):
    path, cfg = cfg_file
    cfg["budget"]["max_usd"] = 0.0015  # one fake call costs $0.00152 on Haiku
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    fake = FakeClient()
    run_module.main(["--config", str(path), "--run", "b", "--countries", "Poland", "Japan", "--samples", "2"],
                    client=fake)
    assert len(fake.requests) == 1


FULL_TRIAL = 2 + 3 * 3 * 2 + 3 * 2  # round 0 + judge; C1, C2, C5 x 3 rounds x (revise + judge); C3 x 3 x (draw + judge)


def test_full_run_makes_every_planned_call(cfg_file, tmp_path, capsys):
    path, _ = cfg_file
    fake = FakeClient(stretch=1.2)
    args = ["--config", str(path), "--run", "f", "--countries", "Poland", "Lesotho", "--samples", "1"]
    run_module.main(args, client=fake)
    rows = read_log(tmp_path, "f")
    assert len(rows) == 2 * FULL_TRIAL == len(fake.requests)
    countries = run_module.select_countries(["Poland", "Lesotho"])
    assert [run_module.key(r) for r in rows] == run_module.plan(countries, 1, ["C0", "C1", "C2", "C3", "C5"], 3, True)
    out = capsys.readouterr().out
    assert "Mean IoU" in out and "C3 resample, judge pick" in out and "round 3" in out


def test_resume_mid_trial_after_budget_stop(cfg_file, tmp_path):
    path, cfg = cfg_file
    cfg["budget"]["max_usd"] = 0.012  # stops partway through the first trial
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    args = ["--config", str(path), "--run", "r", "--countries", "Poland", "--samples", "1"]
    fake = FakeClient()
    run_module.main(args, client=fake)
    first = len(fake.requests)
    assert 0 < first < FULL_TRIAL

    cfg["budget"]["max_usd"] = 20.0
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    run_module.main(args, client=fake)
    rows = read_log(tmp_path, "r")
    assert len(rows) == FULL_TRIAL == len(fake.requests)
    assert len({run_module.key(r) for r in rows}) == FULL_TRIAL  # nothing logged twice


def test_dry_run_counts_calls_and_estimates_cost(cfg_file, tmp_path, capsys):
    path, _ = cfg_file
    run_module.main(["--config", str(path), "--run", "dry", "--countries", "Poland", "--samples", "2", "--dry-run"],
                    client=FakeClient())
    out = capsys.readouterr().out
    assert f"{2 * FULL_TRIAL} calls to make" in out and "guessed tokens" in out
    assert "C1 revise     6" in out and "C3 draw       6" in out
    assert not (tmp_path / "runs" / "dry").exists()  # a dry run leaves no folder behind


def test_thinking_tokens_read_from_usage():
    from llm import thinking_tokens
    assert thinking_tokens(SimpleNamespace(output_tokens_details=SimpleNamespace(thinking_tokens=3406))) == 3406
    assert thinking_tokens(SimpleNamespace(output_tokens_details={"thinking_tokens": 12})) == 12
    assert thinking_tokens(SimpleNamespace(output_tokens_details={"thinking_tokens": None})) is None
    assert thinking_tokens(SimpleNamespace(input_tokens=1)) is None  # no breakdown reported


class ThinkingClient(FakeClient):
    """FakeClient whose usage reports thinking tokens, as Sonnet 5.5 does (D-032)."""

    def create(self, **kw):
        resp = super().create(**kw)
        resp.usage.output_tokens_details = SimpleNamespace(thinking_tokens=2500)
        return resp


def test_thinking_tokens_are_logged(cfg_file, tmp_path):
    path, _ = cfg_file
    one = ["--config", str(path), "--countries", "Poland", "--samples", "1", "--conditions", "C0"]
    run_module.main(one + ["--run", "th"], client=ThinkingClient())
    run_module.main(one + ["--run", "no"], client=FakeClient())
    assert all(r["thinking_tokens"] == 2500 for r in read_log(tmp_path, "th"))  # drawing and judge rows
    assert all(r["thinking_tokens"] is None for r in read_log(tmp_path, "no"))
