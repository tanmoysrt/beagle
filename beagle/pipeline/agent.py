from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import ReviewCfg
from ..errors import ProviderError
from ..llm.client import Budget, LLMClient, Reply
from .schemas import read_entries, report_findings_schema
from .tools import TOOL_SPECS, Toolbox

log = logging.getLogger("beagle.pipeline.agent")

REPORT_TOOL = "report_findings"
# Turns beyond the step budget, for the report itself and for one nudge.
SPARE_TURNS = 3
STEP_MAX_TOKENS = 3000
REPORT_MAX_TOKENS = 8000
TRANSCRIPT_RESULT_CHARS = 2000
BRIEF_CHARS = 120


@dataclass
class Step:
    tool: str
    arguments: dict[str, Any]
    result: str

    @property
    def query(self) -> str:
        return ", ".join(f"{key}={value}" for key, value in self.arguments.items())[:BRIEF_CHARS]

    def brief(self) -> str:
        lines = self.result.splitlines()
        head = lines[0][:BRIEF_CHARS] if lines else ""
        return f"{head} (+{len(lines) - 1} lines)" if len(lines) > 1 else head

    def render(self) -> str:
        return f"{self.tool}({self.query})\n{self.result[:TRANSCRIPT_RESULT_CHARS]}"


@dataclass
class Investigation:
    """What the reviewer looked at, in the order it looked."""

    opening: str = ""
    steps: list[Step] = field(default_factory=list)
    stopped: str = ""

    def evidence(self) -> list[dict[str, str]]:
        return [
            {"tool": step.tool, "input": step.query, "result": step.brief()}
            for step in self.steps
        ]

    def transcript(self) -> str:
        parts = [self.opening] + [step.render() for step in self.steps]
        if self.stopped:
            parts.append(f"(the investigation stopped: {self.stopped})")
        return "\n\n".join(parts)

    def label(self) -> str:
        if not self.steps:
            return "diff"
        return f"diff+{len(self.steps)} tool call(s)"


class AgentReviewer:
    """Reviews one unit as a loop: read the diff, investigate, then report.

    The model chooses what to read, so the cost of a unit follows how hard the
    change is rather than a fixed context budget. The step budget and the input
    token cap end the loop; a forced report keeps whatever it has by then.
    """

    def __init__(self, client: LLMClient, prompts, cfg: ReviewCfg):
        self.client = client
        self.prompts = prompts
        self.cfg = cfg

    def review(
        self,
        unit,
        diff_text: str,
        toolbox: Toolbox,
        system: list[dict],
        review_id: str,
        budget: Budget | None = None,
        on_step: Callable[[Step], None] | None = None,
    ) -> tuple[list[dict], list[str], Investigation]:
        trail = Investigation(opening=self.opening(unit, diff_text))
        messages: list[dict[str, Any]] = [{"role": "user", "content": trail.opening}]
        anomalies: list[str] = []
        force = self.cfg.max_steps <= 0

        for _ in range(self.cfg.max_steps + SPARE_TURNS):
            try:
                reply = self.turn(system, messages, review_id, unit.key, budget, force)
            except ProviderError as exc:
                anomalies.append(f"{unit.key}: the reviewer stopped early ({exc})")
                break

            report = next(
                (call for call in reply.tool_calls if call["name"] == REPORT_TOOL), None
            )
            if report is not None:
                entries, anomaly = read_entries(report["input"], "findings")
                if anomaly:
                    anomalies.append(f"{unit.key}: {anomaly}")
                return entries, anomalies, trail

            if force:
                anomalies.append(f"{unit.key}: the reviewer never reported")
                break
            if not reply.blocks:
                force = True
                continue

            calls = [call for call in reply.tool_calls if call["name"] != REPORT_TOOL]
            results = self.act_all(calls, toolbox, trail, on_step)
            trail.stopped = self.spent(trail, reply.usage.tokens_in)
            force = bool(trail.stopped) or not calls

            messages.append({"role": "assistant", "content": reply.blocks})
            messages.append({"role": "user", "content": results + [self.note(trail, force)]})

        return [], anomalies, trail

    def turn(
        self,
        system: list[dict],
        messages: list[dict],
        review_id: str,
        unit: str,
        budget: Budget | None,
        force: bool,
    ) -> Reply:
        return self.client.converse(
            tier="reasoning",
            system=system,
            messages=messages,
            tools=TOOL_SPECS + [self.report_spec()],
            # The findings need room. A turn that only picks the next tool does
            # not, and a reasoning model will fill whatever room it is given.
            max_tokens=REPORT_MAX_TOKENS if force else STEP_MAX_TOKENS,
            force_tool=REPORT_TOOL if force else None,
            prompt_name="reviewer",
            review_id=review_id,
            unit=unit,
            budget=budget,
        )

    def act_all(
        self,
        calls: list[dict],
        toolbox: Toolbox,
        trail: Investigation,
        on_step: Callable[[Step], None] | None,
    ) -> list[dict]:
        """Every tool call needs an answer, so what the budget refuses says so."""
        room = self.cfg.max_steps - len(trail.steps)
        results = []
        for index, call in enumerate(calls):
            if index >= room:
                results.append(tool_result(call, "the investigation budget is spent"))
                continue
            step = Step(call["name"], call["input"], toolbox.run(call["name"], call["input"]))
            trail.steps.append(step)
            if on_step is not None:
                on_step(step)
            results.append(tool_result(call, step.result))
        return results

    def note(self, trail: Investigation, force: bool) -> dict:
        """A model that cannot see its budget spends all of it, then reports nothing."""
        if force:
            return {
                "type": "text",
                "text": "Your investigation is over. Call report_findings now with every "
                "defect you found, worst first. Report an empty list only if you found none.",
            }
        left = self.cfg.max_steps - len(trail.steps)
        return {
            "type": "text",
            "text": f"{left} of {self.cfg.max_steps} tool calls left. Report as soon as you "
            "can answer, and keep what you have already found.",
        }

    def spent(self, trail: Investigation, tokens: int) -> str:
        if len(trail.steps) >= self.cfg.max_steps:
            return f"{len(trail.steps)} tool calls, the step budget"
        if tokens >= self.cfg.max_input_tokens:
            return f"{tokens} input tokens, the input cap"
        return ""

    def report_spec(self) -> dict:
        return {
            "name": REPORT_TOOL,
            "description": (
                "Report every finding you have, worst first, and end the review. "
                "Call this once, when you have investigated enough. An empty list "
                "is a valid answer."
            ),
            "input_schema": report_findings_schema(self.cfg.categories),
        }

    def opening(self, unit, diff_text: str) -> str:
        header = [f"REVIEW UNIT: {unit.title}", f"Files: {', '.join(unit.paths)}"]
        if unit.risk_tags:
            header.append(f"Risk tags: {', '.join(unit.risk_tags)}")
        if unit.rationale:
            header.append(f"Why these files belong together: {unit.rationale}")
        return "\n".join(header) + f"\n\nCHANGED CODE UNDER REVIEW\n\n{diff_text}"


def tool_result(call: dict, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": call["id"], "content": content}
