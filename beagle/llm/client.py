from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ..config import LLMCfg, ReviewCfg
from ..constants import PROMPT_SET_VERSION, REVIEW_DEADLINE_SECONDS
from ..errors import BudgetExceeded, ProviderError
from ..storage.dao import CallLog

# Rough per-million-token rates, used only for budget accounting and the cost
# line in a review. Operators on a gateway can be billed differently.
# in, out, and the share of the input rate that a cached read costs. The first
# key that appears in the model name wins, so put the specific names first.
# Rough rates for budget accounting only; a gateway may bill differently.
PRICES = {
    "deepseek-v4-flash-0731": (0.14, 0.28, 0.02),
    "deepseek-v4-flash": (0.14, 0.28, 0.20),
    "deepseek-v4-pro": (0.435, 0.87, 0.01),
    "deepseek-v3.2": (0.27, 0.40, 0.50),
    "deepseek": (0.30, 1.00, 0.20),
    "kimi-k2.7-code": (0.73, 3.50, 0.21),
    "kimi": (0.60, 2.50, 0.25),
    "glm-5.2": (0.76, 2.39, 0.19),
    "glm-4.7": (0.40, 1.75, 0.20),
    "glm": (0.95, 2.55, 0.21),
    "haiku": (1.00, 5.00, 0.10),
    "sonnet": (3.00, 15.00, 0.10),
    "opus": (5.00, 25.00, 0.10),
}


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.tokens_cached += other.tokens_cached
        self.cost_usd += other.cost_usd
        self.calls += other.calls


@dataclass
class Reply:
    data: dict[str, Any]
    text: str
    usage: Usage
    model: str
    stop_reason: str | None = None
    reused: bool = False


@dataclass
class Budget:
    """Stops a review before it spends more money or time than allowed."""

    max_cost_usd: float
    token_budget: int
    deadline_seconds: float = REVIEW_DEADLINE_SECONDS
    spent: Usage = field(default_factory=Usage)
    started: float = field(default_factory=time.monotonic)
    reuse: bool = True
    reused: int = 0

    def check(self) -> None:
        if self.spent.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(
                f"review stopped at ${self.spent.cost_usd:.2f} of ${self.max_cost_usd:.2f}"
            )
        if self.spent.tokens_in + self.spent.tokens_out >= self.token_budget:
            raise BudgetExceeded(f"review stopped at the {self.token_budget} token budget")
        elapsed = time.monotonic() - self.started
        if elapsed >= self.deadline_seconds:
            raise BudgetExceeded(
                f"review stopped after {elapsed / 60:.1f} minutes (deadline "
                f"{self.deadline_seconds / 60:.0f} minutes)"
            )

    def record(self, usage: Usage) -> None:
        self.spent.add(usage)


class LLMClient:
    """Anthropic-compatible client with schema-enforced output and call logging.

    base_url and extra headers come from config so a gateway or proxy works
    without code changes; Beagle's own cache-control headers are never replaced.
    """

    def __init__(self, cfg: LLMCfg, call_log: CallLog | None = None, timeout: float = 300.0):
        self.cfg = cfg
        self.call_log = call_log
        self.client = anthropic.Anthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            default_headers=dict(cfg.headers),
            timeout=timeout,
            max_retries=3,
        )

    def model_for(self, tier: str) -> str:
        return getattr(self.cfg.models, tier)

    def structured(
        self,
        tier: str,
        system: list[dict[str, Any]],
        user: str,
        schema: dict[str, Any],
        tool_name: str,
        max_tokens: int = 8000,
        prompt_name: str | None = None,
        review_id: str | None = None,
        unit: str | None = None,
        budget: Budget | None = None,
    ) -> Reply:
        """One call that must answer with a value matching the schema."""
        if budget is not None:
            budget.check()
        model = self.model_for(tier)
        request = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": tool_name,
                    "description": f"Return the {tool_name} result.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
            # A reasoning model behind a gateway thinks until max_tokens is gone and
            # then emits an empty tool call. The schema is the place to reason.
            "thinking": {"type": "disabled"},
        }
        reply = self.send(
            request, prompt_name, review_id, unit, reuse=budget is None or budget.reuse
        )
        if budget is not None:
            budget.record(reply.usage)
            budget.reused += int(reply.reused)
        return reply

    def send(
        self,
        request: dict[str, Any],
        prompt_name: str | None = None,
        review_id: str | None = None,
        unit: str | None = None,
        reuse: bool = True,
    ) -> Reply:
        started = time.monotonic()
        if reuse:
            stored = self.stored_reply(request)
            if stored is not None:
                return stored
        try:
            message = self.client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            if self.thinking_conflict(exc, request):
                return self.send(disable_thinking(request), prompt_name, review_id, unit)
            if self.thinking_unsupported(exc, request):
                return self.send(without_thinking(request), prompt_name, review_id, unit)
            self.log(request, None, started, prompt_name, review_id, unit, error=str(exc))
            raise ProviderError(
                f"llm request failed ({exc.status_code}): {short(str(exc))}",
                status=exc.status_code,
                retryable=exc.status_code in (408, 429, 500, 502, 503, 529),
            ) from exc
        except anthropic.APIError as exc:
            self.log(request, None, started, prompt_name, review_id, unit, error=str(exc))
            raise ProviderError(f"llm request failed: {short(str(exc))}") from exc

        reply = self.build_reply(message, request)
        self.log(request, message, started, prompt_name, review_id, unit)
        return reply

    def stored_reply(self, request: dict[str, Any]) -> Reply | None:
        """The same question asked before deserves the same answer, at no cost.

        Every input the model saw is inside the hash, so a new model, an edited
        prompt or a changed rule all miss and go to the service.
        """
        if self.call_log is None:
            return None
        data = self.call_log.find(request_hash(request), PROMPT_SET_VERSION)
        if data is None:
            return None
        payload, text = {}, ""
        for block in data.get("content") or []:
            if block.get("type") == "tool_use":
                payload = dict(block.get("input") or {})
            elif block.get("type") == "text":
                text += block.get("text") or ""
        if request.get("tool_choice") and not payload:
            return None
        return Reply(payload, text, Usage(), data.get("model", request["model"]),
                     data.get("stop_reason"), reused=True)

    def thinking_conflict(self, exc: anthropic.APIStatusError, request: dict) -> bool:
        """Some models reject a forced tool choice while thinking is on."""
        text = str(exc).lower()
        return (
            exc.status_code == 400
            and "thinking" in text
            and "tool_choice" in request
            and "thinking" not in request
        )

    def thinking_unsupported(self, exc: anthropic.APIStatusError, request: dict) -> bool:
        """And some reject the field that turns thinking off."""
        return exc.status_code == 400 and "thinking" in str(exc).lower() and "thinking" in request

    def build_reply(self, message: Any, request: dict) -> Reply:
        usage = self.usage_of(message, request["model"])
        data, text = {}, ""
        for block in message.content:
            if block.type == "tool_use":
                data = dict(block.input)
            elif block.type == "text":
                text += block.text
        if request.get("tool_choice") and not data:
            raise ProviderError(
                f"model {request['model']} returned no structured result "
                f"(stop reason: {message.stop_reason})"
            )
        return Reply(data, text, usage, message.model, message.stop_reason)

    def usage_of(self, message: Any, model: str) -> Usage:
        raw = message.usage
        cached = (getattr(raw, "cache_read_input_tokens", 0) or 0)
        created = (getattr(raw, "cache_creation_input_tokens", 0) or 0)
        tokens_in = (raw.input_tokens or 0) + created + cached
        return Usage(
            tokens_in=tokens_in,
            tokens_out=raw.output_tokens or 0,
            tokens_cached=cached,
            cost_usd=estimate_cost(model, tokens_in - cached, cached, raw.output_tokens or 0),
            calls=1,
        )

    def log(
        self,
        request: dict,
        message: Any,
        started: float,
        prompt_name: str | None,
        review_id: str | None,
        unit: str | None,
        error: str | None = None,
    ) -> None:
        if self.call_log is None:
            return
        usage = self.usage_of(message, request["model"]) if message else Usage()
        self.call_log.record(
            request_hash=request_hash(request),
            model=request["model"],
            request=redact_request(request),
            response=message.model_dump() if message is not None else None,
            prompt_name=prompt_name,
            prompt_set_version=PROMPT_SET_VERSION,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            tokens_cached=usage.tokens_cached,
            cost_usd=usage.cost_usd,
            latency_ms=int((time.monotonic() - started) * 1000),
            review_id=review_id,
            unit=unit,
            error=error,
        )


def make_budget(review: ReviewCfg) -> Budget:
    return Budget(max_cost_usd=review.max_cost_usd, token_budget=review.token_budget)


def disable_thinking(request: dict) -> dict:
    return {**request, "thinking": {"type": "disabled"}}


def without_thinking(request: dict) -> dict:
    return {key: value for key, value in request.items() if key != "thinking"}


def estimate_cost(model: str, fresh_in: int, cached_in: int, out: int) -> float:
    name = model.lower()
    for key, (price_in, price_out, cached_ratio) in PRICES.items():
        if key in name:
            return round(
                (fresh_in * price_in + cached_in * price_in * cached_ratio + out * price_out)
                / 1_000_000,
                6,
            )
    return 0.0


def request_hash(request: dict) -> str:
    payload = json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def redact_request(request: dict) -> dict:
    """Keep the prompt for replay, drop nothing but keep the record bounded."""
    return {
        "model": request["model"],
        "max_tokens": request.get("max_tokens"),
        "system": request.get("system"),
        "messages": request.get("messages"),
        "tool": (request.get("tool_choice") or {}).get("name"),
    }


def short(text: str, limit: int = 300) -> str:
    return text[:limit].replace("\n", " ")
