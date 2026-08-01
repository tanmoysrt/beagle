from __future__ import annotations

from ..config import ReviewCfg, Severity
from ..constants import P4_CAP, P5_CAP
from ..llm.client import Budget, LLMClient
from ..prompts.loader import PromptSet, dedup_values
from .models import Finding, normalize
from .review import clamp, coerce_severity, read_locations
from .schemas import OUTPUT_INSTRUCTIONS, read_entries, report_findings_schema


class Merger:
    """Collapses repeats and enforces the caps that keep reviews short.

    Security findings pass through untouched: they are never merged away,
    never capped, and never dropped by the severity floor.
    """

    def __init__(self, client: LLMClient, prompts: PromptSet, cfg: ReviewCfg):
        self.client = client
        self.prompts = prompts
        self.cfg = cfg

    def merge(
        self, findings: list[Finding], review_id: str, budget: Budget | None = None
    ) -> tuple[list[Finding], int]:
        security = [item for item in findings if item.is_security]
        ordinary = [item for item in findings if not item.is_security]

        ordinary = collapse_identical(ordinary)
        if len(ordinary) > 1:
            ordinary = self.model_merge(ordinary, review_id, budget) or ordinary

        ordinary = [item for item in ordinary if item.severity.at_least(self.cfg.min_severity)]
        ordinary = apply_level_caps(ordinary)
        kept, overflow = apply_total_cap(ordinary, self.cfg.max_findings)
        return security + kept, overflow

    def model_merge(
        self, findings: list[Finding], review_id: str, budget: Budget | None
    ) -> list[Finding] | None:
        system = self.prompts.get("dedup").render(dedup_values(OUTPUT_INSTRUCTIONS["dedup"]))
        try:
            reply = self.client.structured(
                tier="haiku",
                system=[{"type": "text", "text": system}],
                user=render_findings(findings),
                schema=report_findings_schema(self.cfg.categories),
                tool_name="report_findings",
                max_tokens=6000,
                prompt_name="dedup",
                review_id=review_id,
                budget=budget,
            )
        except Exception:
            return None  # merging is an optimisation, never a blocker

        by_title = {normalize(item.title): item for item in findings}
        entries, _ = read_entries(reply.data, "findings")
        merged = [
            self.rebuild(raw, by_title.get(normalize(raw["title"])))
            for raw in entries
            if raw.get("title")
        ]
        return merged or None

    def rebuild(self, raw: dict, original: Finding | None) -> Finding:
        severity = coerce_severity(raw.get("severity"))
        locations = read_locations(raw)
        return Finding(
            file=raw.get("file") or (original.file if original else "unknown"),
            line_start=raw.get("line_start"),
            line_end=raw.get("line_end"),
            category=raw.get("category") or (original.category if original else "bug"),
            severity=severity,
            model_severity=original.model_severity if original else severity,
            confidence=clamp(raw.get("confidence", original.confidence if original else 0.5)),
            title=raw.get("title", "").strip(),
            body=raw.get("body", "").strip(),
            suggested_patch=(raw.get("suggested_patch") or "").strip() or None,
            locations=locations or (original.locations if original else []),
            unit=original.unit if original else "merged",
            context_used=original.context_used if original else "",
            metadata=dict(original.metadata) if original else {},
        )


def collapse_identical(findings: list[Finding]) -> list[Finding]:
    """Same fingerprint from two units is one finding with both locations."""
    grouped: dict[str, Finding] = {}
    for finding in findings:
        existing = grouped.get(finding.fingerprint)
        if existing is None:
            grouped[finding.fingerprint] = finding
            continue
        existing.locations.extend(
            location for location in finding.locations if location not in existing.locations
        )
        existing.confidence = max(existing.confidence, finding.confidence)
        if finding.severity.at_least(existing.severity):
            existing.severity = finding.severity
    return list(grouped.values())


def apply_level_caps(findings: list[Finding]) -> list[Finding]:
    caps = {Severity.P5: P5_CAP, Severity.P4: P4_CAP}
    ranked = sorted(findings, key=lambda item: (item.severity.rank, -item.confidence))
    kept, counts = [], {level: 0 for level in caps}
    for finding in ranked:
        cap = caps.get(finding.severity)
        if cap is not None:
            if counts[finding.severity] >= cap:
                continue
            counts[finding.severity] += 1
        kept.append(finding)
    return kept


def apply_total_cap(findings: list[Finding], max_findings: int) -> tuple[list[Finding], int]:
    ranked = sorted(findings, key=lambda item: (item.severity.rank, -item.confidence))
    if len(ranked) <= max_findings:
        return ranked, 0
    return ranked[:max_findings], len(ranked) - max_findings


def render_findings(findings: list[Finding]) -> str:
    blocks = []
    for finding in findings:
        locations = ", ".join(location.label() for location in finding.locations)
        blocks.append(
            f"[{finding.severity.value}] ({finding.category}) {finding.title}\n"
            f"locations: {locations}\nconfidence: {finding.confidence:.2f}\n{finding.body}"
        )
    return "FINDINGS FROM ALL UNITS\n\n" + "\n\n---\n\n".join(blocks)
