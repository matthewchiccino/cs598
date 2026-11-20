"""Claude API wrapper: one request in, text and cost out, with a hard budget cap (D-015).

The runner writes one JSONL row per call through RunLog, so spend survives restarts.
"""
import base64
import json
from dataclasses import dataclass
from pathlib import Path

# USD per million tokens (input, output). Haiku 5.5 rates apply to prompts up to 100K tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class BudgetExceeded(RuntimeError):
    pass


def thinking_off(model: str) -> dict:
    """Request field that turns thinking off for this model."""
    if model.startswith("claude-haiku-5-5"):
        return {"type": "disabled"}
    if model.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}  # no tools are sent, so no thinking happens
    raise ValueError(f"{model}: thinking cannot be turned off; pick another model or set thinking: true")


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICES[model]
    return (input_tokens * inp + output_tokens * out) / 1e6


class RunLog:
    """Append-only JSONL file of call rows for one run."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def append(self, row: dict):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def spent(self) -> float:
        return sum(r.get("cost_usd") or 0 for r in self.rows())


class Budget:
    def __init__(self, max_usd: float, spent: float = 0.0):
        self.max_usd = max_usd
        self.spent = spent

    def check(self):
        if self.spent >= self.max_usd:
            raise BudgetExceeded(f"spent ${self.spent:.4f} of ${self.max_usd:.2f}")

    def add(self, usd: float):
        self.spent += usd


def image_block(png: Path) -> dict:
    data = base64.standard_b64encode(Path(png).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def to_content(parts):
    """A string as is; a list of parts as content blocks: str -> text, Path -> PNG image, dict as given."""
    if isinstance(parts, str):
        return parts
    blocks = []
    for p in parts:
        if isinstance(p, Path):
            blocks.append(image_block(p))
        elif isinstance(p, str):
            blocks.append({"type": "text", "text": p})
        else:
            blocks.append(p)
    return blocks


@dataclass
class Reply:
    text: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    request_id: str | None


class LLM:
    def __init__(self, model_cfg: dict, client=None):
        self.model = model_cfg["name"]
        self.max_tokens = model_cfg.get("max_tokens", 16000)
        self.effort = model_cfg.get("effort")
        self.thinking = model_cfg.get("thinking", False)
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client

    def request_kwargs(self, content) -> dict:
        kw = {"model": self.model, "max_tokens": self.max_tokens,
              "messages": [{"role": "user", "content": to_content(content)}]}
        if self.effort:
            kw["output_config"] = {"effort": self.effort}
        if not self.thinking:
            kw["thinking"] = thinking_off(self.model)
        return kw

    def call(self, content, *, budget: Budget) -> Reply:
        """One user turn (a string, or parts for to_content). Raises BudgetExceeded before spending.

        A refusal comes back as a normal Reply with stop_reason "refusal", so its cost is still logged.
        """
        budget.check()
        resp = self.client.messages.create(**self.request_kwargs(content))
        usage = resp.usage
        usd = cost_usd(self.model, usage.input_tokens, usage.output_tokens)
        budget.add(usd)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return Reply(text, resp.stop_reason, usage.input_tokens, usage.output_tokens, usd,
                     getattr(resp, "_request_id", None))
