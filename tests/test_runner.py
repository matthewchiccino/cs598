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


class FakeClient:
    """Answers each draw request with the reference outline, stretched by `stretch`."""

    def __init__(self, stretch: float = 1.0, text: str | None = None):
        self.stretch, self.text, self.requests = stretch, text, []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        prompt = kw["messages"][0]["content"]
        name = next(c["name"] for c in load_countries() if f"outline of {c['name']} " in prompt)
        spec = next(c for c in load_countries() if c["name"] == name)
        geom = affinity.scale(load_reference(spec), self.stretch, 1.0)
        text = self.text if self.text is not None else f"Here you go:\n{geometry_to_svg(geom)}"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=200, output_tokens=3000), _request_id="req_test")


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    cfg["runs_dir"] = str(tmp_path / "runs")
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


def test_run_logs_scores_and_resumes(cfg_file, tmp_path):
    path, cfg = cfg_file
    fake = FakeClient()
    args = ["--config", str(path), "--run", "t", "--countries", "Poland", "Japan", "--samples", "2"]
    run_module.main(args, client=fake)
    log = tmp_path / "runs" / "t" / "calls.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4 and len(fake.requests) == 4
    assert all(r["valid"] and r["iou"] > 0.99 for r in rows)
    assert all(r["prompt_id"].startswith("draw_v1:") and r["cost_usd"] > 0 for r in rows)
    assert (tmp_path / "runs" / "t" / "round0_gallery.png").exists()

    run_module.main(args, client=fake)  # second run makes no new calls
    assert len(fake.requests) == 4


def test_distorted_and_invalid_replies_are_scored(cfg_file, tmp_path):
    path, _ = cfg_file
    run_module.main(["--config", str(path), "--run", "d", "--countries", "Poland", "--samples", "1"],
                    client=FakeClient(stretch=1.5))
    run_module.main(["--config", str(path), "--run", "x", "--countries", "Poland", "--samples", "1"],
                    client=FakeClient(text="I cannot draw that."))
    d = json.loads((tmp_path / "runs" / "d" / "calls.jsonl").read_text(encoding="utf-8"))
    x = json.loads((tmp_path / "runs" / "x" / "calls.jsonl").read_text(encoding="utf-8"))
    assert d["valid"] and d["iou"] < 0.9
    assert not x["valid"] and x["iou"] == 0 and x["svg"] is None


def test_model_option_overrides_config(cfg_file, tmp_path):
    path, _ = cfg_file
    fake = FakeClient()
    run_module.main(["--config", str(path), "--model", "claude-sonnet-5-5", "--countries", "Poland", "--samples", "1"],
                    client=fake)
    run_dir = tmp_path / "runs" / "pilot_claude-sonnet-5-5"  # default run name is <run_name>_<model>
    row = json.loads((run_dir / "calls.jsonl").read_text(encoding="utf-8"))
    assert row["model"] == "claude-sonnet-5-5"
    assert fake.requests[0]["model"] == "claude-sonnet-5-5"
    assert fake.requests[0]["thinking"] == {"type": "between_tools"}
    assert json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["model"]["name"] == "claude-sonnet-5-5"


def test_opus_needs_thinking_flag(cfg_file, tmp_path):
    path, _ = cfg_file
    base = ["--config", str(path), "--model", "claude-opus-5-5", "--countries", "Poland", "--samples", "1"]
    with pytest.raises(SystemExit, match="--thinking"):
        run_module.main(base, client=FakeClient())
    fake = FakeClient()
    run_module.main(base + ["--thinking"], client=fake)
    assert "thinking" not in fake.requests[0]  # omitted = adaptive thinking
    row = json.loads((tmp_path / "runs" / "pilot_claude-opus-5-5" / "calls.jsonl").read_text(encoding="utf-8"))
    assert row["cost_usd"] == pytest.approx(cost_usd("claude-opus-5-5", 200, 3000))


def test_unknown_model_is_rejected(cfg_file):
    path, _ = cfg_file
    with pytest.raises(SystemExit, match="No price"):
        run_module.main(["--config", str(path), "--model", "claude-made-up", "--dry-run"], client=FakeClient())


def test_same_run_refuses_a_second_model(cfg_file):
    path, _ = cfg_file
    args = ["--config", str(path), "--run", "same", "--countries", "Poland", "--samples", "1"]
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
