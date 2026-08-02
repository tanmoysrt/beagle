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
# Beyond the step budget: the report itself, and one nudge.
SPARE_TURNS = 3
# Output only. A cut off turn carries no tool call, so the room is never worth
# saving.
MAX_TOKENS = 250000
TRANSCRIPT_RESULT_CHARS = 2000
VERDICT = (
    "That is everything you read. Report every defect the change introduces, worst "
    "first. Report an empty list only if the change introduces none."
)
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

    The model chooses what to read, so a unit costs what the change deserves.
    The investigation and the verdict are two questions, not one conversation.
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

        for _ in range(self.cfg.max_steps + SPARE_TURNS):
            try:
                reply = self.turn(system, messages, review_id, unit.key, budget)
            except ProviderError as exc:
                anomalies.append(f"{unit.key}: the investigation stopped early ({exc})")
                break

            report = next(
                (call for call in reply.tool_calls if call["name"] == REPORT_TOOL), None
            )
            if report is not None:
                entries, anomaly = read_entries(report["input"], "findings")
                if anomaly:
                    anomalies.append(f"{unit.key}: {anomaly}")
                return entries, anomalies, trail

            calls = [call for call in reply.tool_calls if call["name"] != REPORT_TOOL]
            cut_off = not calls and reply.stop_reason == "max_tokens"
            if not reply.blocks or (not calls and not cut_off):
                break

            results = self.act_all(calls, toolbox, trail, on_step)
            trail.stopped = self.spent(trail, reply.usage.tokens_in)
            messages.append({"role": "assistant", "content": reply.blocks})
            messages.append({"role": "user", "content": results + [self.note(trail, cut_off)]})
            if trail.stopped:
                break

        entries, anomaly = self.report(trail, system, review_id, unit, budget)
        if anomaly:
            anomalies.append(f"{unit.key}: {anomaly}")
        return entries, anomalies, trail

    def report(
        self,
        trail: Investigation,
        system: list[dict],
        review_id: str,
        unit,
        budget: Budget | None,
    ) -> tuple[list[dict], str | None]:
        """The findings as their own question, not one more turn of the loop."""
        try:
            reply = self.client.structured(
                tier="reasoning",
                system=system,
                user=f"{trail.transcript()}\n\n{VERDICT}",
                schema=report_findings_schema(self.cfg.categories),
                tool_name=REPORT_TOOL,
                max_tokens=MAX_TOKENS,
                prompt_name="reviewer",
                review_id=review_id,
                unit=unit.key,
                budget=budget,
            )
        except ProviderError as exc:
            return [], f"the reviewer never reported ({exc})"
        return read_entries(reply.data, "findings")

    def turn(
        self,
        system: list[dict],
        messages: list[dict],
        review_id: str,
        unit: str,
        budget: Budget | None,
    ) -> Reply:
        return self.client.converse(
            tier="reasoning",
            system=system,
            messages=messages,
            tools=TOOL_SPECS + [self.report_spec()],
            max_tokens=MAX_TOKENS,
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

    def note(self, trail: Investigation, cut_off: bool = False) -> dict:
        """A model that cannot see its budget spends all of it, then reports nothing."""
        if cut_off:
            return {
                "type": "text",
                "text": "Your last answer stopped before you called a tool. Keep the "
                "reasoning short and call the tool you need.",
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
