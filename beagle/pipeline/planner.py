from __future__ import annotations

from ..llm.client import Budget, LLMClient
from ..prompts.loader import PromptSet, plan_values
from ..repo.diff import FileDiff
from .models import ReviewUnit
from .schemas import OUTPUT_INSTRUCTIONS, PLAN_UNITS_SCHEMA, read_entries

MAX_UNITS = 6
SINGLE_UNIT_THRESHOLD = 2


class Planner:
    """Groups changed files into coherent review units and tags risk."""

    def __init__(self, client: LLMClient, prompts: PromptSet):
        self.client = client
        self.prompts = prompts

    def plan(
        self, diffs: list[FileDiff], review_id: str, budget: Budget | None = None
    ) -> list[ReviewUnit]:
        if len(diffs) <= SINGLE_UNIT_THRESHOLD:
            return [self.single_unit(diffs)]

        system = self.prompts.get("plan").render(
            plan_values(MAX_UNITS, OUTPUT_INSTRUCTIONS["plan"])
        )
        reply = self.client.structured(
            tier="general",
            system=[{"type": "text", "text": system}],
            user=describe(diffs),
            schema=PLAN_UNITS_SCHEMA,
            tool_name="plan_units",
            max_tokens=2000,
            prompt_name="plan",
            review_id=review_id,
            budget=budget,
        )
        units = self.units_from(reply.data, {item.path for item in diffs})
        return units or [self.single_unit(diffs)]

    def units_from(self, data: dict, known_paths: set[str]) -> list[ReviewUnit]:
        units, claimed = [], set()
        entries, _ = read_entries(data, "units")
        for index, raw in enumerate(entries[:MAX_UNITS]):
            paths = [path for path in raw.get("paths", []) if path in known_paths]
            if not paths:
                continue
            units.append(
                ReviewUnit(
                    key=f"unit-{index + 1}",
                    title=raw.get("title") or f"unit {index + 1}",
                    paths=paths,
                    risk_tags=list(raw.get("risk_tags", [])),
                    rationale=raw.get("rationale", ""),
                )
            )
            claimed.update(paths)

        missed = sorted(known_paths - claimed)
        if missed:
            units.append(ReviewUnit(key=f"unit-{len(units) + 1}", title="remaining files", paths=missed))
        return units

    def single_unit(self, diffs: list[FileDiff]) -> ReviewUnit:
        return ReviewUnit(
            key="unit-1",
            title="the change",
            paths=[item.path for item in diffs],
        )


def describe(diffs: list[FileDiff]) -> str:
    lines = ["Changed files:"]
    for item in diffs:
        # no line counts: they change on every edit and would regroup the units
        lines.append(f"- {item.path} ({item.status})")
    return "\n".join(lines)
