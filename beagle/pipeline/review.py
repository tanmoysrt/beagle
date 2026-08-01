from __future__ import annotations

from ..config import ReviewCfg, Severity
from ..llm.client import Budget, LLMClient
from ..prompts.loader import PromptSet, reviewer_values
from .context import UnitContext
from .models import Finding, Location, ReviewUnit
from .schemas import OUTPUT_INSTRUCTIONS, read_entries, report_findings_schema


class UnitReviewer:
    """Runs one review unit and turns the model's answer into findings."""

    def __init__(self, client: LLMClient, prompts: PromptSet, cfg: ReviewCfg):
        self.client = client
        self.prompts = prompts
        self.cfg = cfg

    def cached_prefix(
        self, repo_overview: str, instruction_block: str, conventions: str
    ) -> list[dict]:
        """System blocks that stay byte-identical across every call in a review."""
        system = self.prompts.get("reviewer").render(
            reviewer_values(
                repo_overview=repo_overview,
                instruction_files=instruction_block or "(no repository instruction files found)",
                conventions=conventions or "(no learned conventions yet)",
                output_instructions=OUTPUT_INSTRUCTIONS["reviewer"],
            )
        )
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def review(
        self,
        unit: ReviewUnit,
        context: UnitContext,
        system: list[dict],
        review_id: str,
        budget: Budget | None = None,
    ) -> tuple[list[Finding], list[str]]:
        reply = self.client.structured(
            tier="reasoning",
            system=system,
            user=self.user_message(unit, context),
            schema=report_findings_schema(self.cfg.categories),
            tool_name="report_findings",
            max_tokens=8000,
            prompt_name="reviewer",
            review_id=review_id,
            unit=unit.key,
            budget=budget,
        )
        entries, anomaly = read_entries(reply.data, "findings")
        findings = [
            finding
            for finding in (self.finding_from(raw, unit, context, tier) for raw in entries)
            if finding is not None
        ]
        return findings, [f"{unit.key}: {anomaly}"] if anomaly else []

    def user_message(self, unit: ReviewUnit, context: UnitContext) -> str:
        header = [f"REVIEW UNIT: {unit.title}", f"Files: {', '.join(unit.paths)}"]
        if unit.risk_tags:
            header.append(f"Risk tags: {', '.join(unit.risk_tags)}")
        if unit.rationale:
            header.append(f"Why these files belong together: {unit.rationale}")
        return "\n".join(header) + "\n\n" + context.render()

    def finding_from(
        self, raw: dict, unit: ReviewUnit, context: UnitContext, tier: str
    ) -> Finding | None:
        title = (raw.get("title") or "").strip()
        body = (raw.get("body") or "").strip()
        if not title or not body:
            return None
        severity = coerce_severity(raw.get("severity"))
        locations = read_locations(raw)
        return Finding(
            file=raw.get("file") or unit.paths[0],
            line_start=raw.get("line_start"),
            line_end=raw.get("line_end"),
            category=raw.get("category") or "bug",
            severity=severity,
            model_severity=severity,
            confidence=clamp(raw.get("confidence", 0.5)),
            title=title,
            body=body,
            suggested_patch=(raw.get("suggested_patch") or "").strip() or None,
            locations=locations,
            unit=unit.key,
            context_used=context_label(context),
            metadata={"tier": tier, "risk_tags": unit.risk_tags},
        )


def read_locations(raw: dict) -> list[Location]:
    entries, _ = read_entries(raw, "locations")
    return [
        Location(item["file"], item.get("line_start"), item.get("line_end"))
        for item in entries
        if item.get("file")
    ]


def coerce_severity(value: str | None) -> Severity:
    try:
        return Severity(str(value).upper())
    except ValueError:
        return Severity.P3


def clamp(value: float | int | None) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def context_label(context: UnitContext) -> str:
    parts = ["diff"]
    if context.neighbours:
        parts.append("call graph")
    if context.similar:
        parts.append("retrieved code")
    if context.truncated:
        parts.append("truncated")
    return "+".join(parts)
