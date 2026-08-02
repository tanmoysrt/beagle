from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import ProviderError
from ..llm.client import Budget, LLMClient
from .schemas import OUTPUT_INSTRUCTIONS, SUBMIT_CONTEXT_SCHEMA, read_entries
from .tools import TOOL_SPECS, Toolbox

log = logging.getLogger("beagle.pipeline.investigate")

SUBMIT_TOOL = "submit_context"
MAX_STEPS = 8
SPARE_TURNS = 2
MAX_TOKENS = 8000
MAX_EXCERPTS = 8
MAX_EXCERPT_LINES = 60
MAX_NOTES = 6
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


@dataclass
class Package:
    """Code the investigator asked for, read back from the repository."""

    excerpts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = list(self.excerpts)
        if self.notes:
            parts.append("NOTES\n" + "\n".join(f"- {note}" for note in self.notes))
        return "\n\n".join(parts)

    def evidence(self) -> list[dict[str, str]]:
        return [
            {"tool": step.tool, "input": step.query, "result": step.brief()}
            for step in self.steps
        ]


class Investigator:
    """Reads the repository so the reviewer does not have to.

    It answers with line ranges, never with code: every excerpt is read back
    from the repository, so nothing it writes can reach the reviewer as if it
    were the source.
    """

    def __init__(self, client: LLMClient, prompts):
        self.client = client
        self.prompts = prompts

    def gather(
        self,
        unit,
        diff_text: str,
        known: str,
        toolbox: Toolbox,
        review_id: str,
        budget: Budget | None = None,
        on_step: Callable[[Step], None] | None = None,
    ) -> Package:
        package = Package()
        system = [{"type": "text", "text": self.system_prompt()}]
        opening = self.opening(unit, diff_text, known)
        messages: list[dict[str, Any]] = [{"role": "user", "content": opening}]

        for _ in range(MAX_STEPS + SPARE_TURNS):
            try:
                reply = self.turn(system, messages, review_id, unit.key, budget)
            except ProviderError as exc:
                package.degraded.append(f"{unit.key}: the investigation failed ({exc})")
                return package

            submitted = next(
                (call for call in reply.tool_calls if call["name"] == SUBMIT_TOOL), None
            )
            if submitted is not None:
                self.fill(package, submitted["input"], toolbox)
                return package

            calls = [call for call in reply.tool_calls if call["name"] != SUBMIT_TOOL]
            if not reply.blocks or not calls:
                break

            results = []
            for call in calls[: MAX_STEPS - len(package.steps)]:
                step = Step(call["name"], call["input"], toolbox.run(call["name"], call["input"]))
                package.steps.append(step)
                if on_step is not None:
                    on_step(step)
                results.append(
                    {"type": "tool_result", "tool_use_id": call["id"], "content": step.result}
                )
            if len(calls) > len(results):
                results.extend(
                    {"type": "tool_result", "tool_use_id": call["id"],
                     "content": "the investigation budget is spent"}
                    for call in calls[len(results):]
                )
            messages.append({"role": "assistant", "content": reply.blocks})
            messages.append({"role": "user", "content": results + [self.note(package)]})
            if len(package.steps) >= MAX_STEPS:
                break

        self.submit(package, system, opening, review_id, unit, budget, toolbox)
        return package

    def submit(self, package, system, opening, review_id, unit, budget, toolbox) -> None:
        """The reading is over; ask once for what mattered."""
        try:
            reply = self.client.structured(
                tier="general",
                system=system,
                user=self.closing(opening, package),
                schema=SUBMIT_CONTEXT_SCHEMA,
                tool_name=SUBMIT_TOOL,
                max_tokens=MAX_TOKENS,
                prompt_name="investigator",
                review_id=review_id,
                unit=unit.key,
                budget=budget,
            )
        except ProviderError as exc:
            package.degraded.append(f"{unit.key}: the investigation failed ({exc})")
            return
        self.fill(package, reply.data, toolbox)

    def fill(self, package: Package, data: dict, toolbox: Toolbox) -> None:
        """Resolve the line ranges against the repository, and keep the notes."""
        items, _ = read_entries(data, "items")
        for item in items[:MAX_EXCERPTS]:
            excerpt = self.excerpt(item, toolbox)
            if excerpt:
                package.excerpts.append(excerpt)
        notes = data.get("notes")
        if isinstance(notes, list):
            package.notes = [str(note) for note in notes if isinstance(note, str)][:MAX_NOTES]

    def excerpt(self, item: dict, toolbox: Toolbox) -> str | None:
        path = (item.get("path") or "").strip()
        if not path:
            return None
        start = max(1, int(item.get("start_line") or 1))
        end = int(item.get("end_line") or start)
        end = max(start, min(end, start + MAX_EXCERPT_LINES - 1))
        body = toolbox.run("read_file", {"path": path, "start_line": start, "end_line": end})
        why = (item.get("why") or "").strip()
        return f"# {path}:{start}-{end}{f' — {why}' if why else ''}\n{body}"

    def turn(self, system, messages, review_id, unit, budget):
        return self.client.converse(
            tier="general",
            system=system,
            messages=messages,
            tools=TOOL_SPECS + [self.submit_spec()],
            max_tokens=MAX_TOKENS,
            prompt_name="investigator",
            review_id=review_id,
            unit=unit,
            budget=budget,
        )

    def submit_spec(self) -> dict:
        return {
            "name": SUBMIT_TOOL,
            "description": (
                "Hand over the context you gathered and end the search. Give line "
                "ranges, never code: the ranges are read from the repository."
            ),
            "input_schema": SUBMIT_CONTEXT_SCHEMA,
        }

    def note(self, package: Package) -> dict:
        left = MAX_STEPS - len(package.steps)
        return {
            "type": "text",
            "text": f"{left} of {MAX_STEPS} tool calls left. Call {SUBMIT_TOOL} as soon as "
            "you have what the reviewer needs.",
        }

    def system_prompt(self) -> str:
        return self.prompts.get("investigator").render(
            {"max_steps": str(MAX_STEPS), "output_instructions": OUTPUT_INSTRUCTIONS["investigator"]}
        )

    def opening(self, unit, diff_text: str, known: str) -> str:
        header = [f"REVIEW UNIT: {unit.title}", f"Files: {', '.join(unit.paths)}"]
        if unit.risk_tags:
            header.append(f"Risk tags: {', '.join(unit.risk_tags)}")
        parts = ["\n".join(header), f"CHANGED CODE\n\n{diff_text}"]
        if known:
            parts.append(f"THE REVIEWER ALREADY HAS THIS, SO DO NOT FETCH IT AGAIN\n\n{known}")
        return "\n\n".join(parts)

    def closing(self, opening: str, package: Package) -> str:
        read = "\n\n".join(
            f"{step.tool}({step.query})\n{step.result[:1500]}" for step in package.steps
        )
        return (
            f"{opening}\n\nWHAT YOU READ\n\n{read}\n\n"
            "That is everything. Hand over what the reviewer needs."
        )
