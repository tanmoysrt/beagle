from __future__ import annotations

from ..config import ReviewCfg, Severity
from ..llm.client import Budget, LLMClient
from ..prompts.loader import PromptSet, summary_values
from .models import Finding, ReviewSummary, count_by_severity, score_for, verdict_for
from .schemas import OUTPUT_INSTRUCTIONS, SUMMARY_SCHEMA


class Summariser:
    """Writes the review summary and scores how much to trust it."""

    def __init__(self, client: LLMClient, prompts: PromptSet, cfg: ReviewCfg):
        self.client = client
        self.prompts = prompts
        self.cfg = cfg

    def build(
        self,
        findings: list[Finding],
        diff_digest: str,
        coverage: float,
        review_id: str,
        budget: Budget | None = None,
    ) -> ReviewSummary:
        summary = ReviewSummary(
            counts=count_by_severity(findings),
            coverage=round(coverage, 3),
            verdict=verdict_for(findings, self.cfg.fail_on),
            score=score_for(findings, coverage),
            confidence=overall_confidence(findings, coverage),
        )
        data = self.ask_model(findings, diff_digest, review_id, budget)
        if isinstance(data, dict):
            summary.description = data.get("description", "").strip()
            summary.reasoning = data.get("reasoning", "").strip()
            summary.attention = [
                item for item in data.get("attention", []) if isinstance(item, str)
            ][:2]
            summary.notes = [item for item in data.get("notes", []) if isinstance(item, str)]
        summary.notes.extend(self.security_notes(findings))
        return summary

    def ask_model(
        self, findings: list[Finding], diff_digest: str, review_id: str, budget: Budget | None
    ) -> dict | None:
        system = self.prompts.get("summary").render(
            summary_values(self.cfg.fail_on, OUTPUT_INSTRUCTIONS["summary"])
        )
        try:
            reply = self.client.structured(
                tier="haiku",
                system=[{"type": "text", "text": system}],
                user=self.brief(findings, diff_digest),
                schema=SUMMARY_SCHEMA,
                tool_name="write_summary",
                max_tokens=1500,
                prompt_name="summary",
                review_id=review_id,
                budget=budget,
            )
            return reply.data
        except Exception:
            return None

    def brief(self, findings: list[Finding], diff_digest: str) -> str:
        lines = [diff_digest, "", "FINAL FINDINGS:"]
        if not findings:
            lines.append("(none)")
        for finding in findings:
            lines.append(
                f"- [{finding.severity.value}] {finding.file}: {finding.title} "
                f"(confidence {finding.confidence:.2f})"
            )
        return "\n".join(lines)

    def security_notes(self, findings: list[Finding]) -> list[str]:
        notes = []
        for finding in findings:
            if finding.is_security and finding.app_code is False:
                notes.append(
                    f"Security finding in non-application code kept at "
                    f"{finding.severity.value}: {finding.file}"
                )
            elif finding.metadata.get("severity_forced"):
                notes.append(
                    f"Security finding in application code raised from "
                    f"{finding.metadata['severity_forced']} to P0: {finding.file}"
                )
        return notes


def overall_confidence(findings: list[Finding], coverage: float) -> float:
    """A truncated review scores lower even when its findings look solid."""
    if not findings:
        return round(0.6 * coverage + 0.4, 3)
    weights = {Severity.P0: 3.0, Severity.P1: 2.5, Severity.P2: 2.0}
    total = sum(weights.get(item.severity, 1.0) for item in findings)
    weighted = sum(weights.get(item.severity, 1.0) * item.confidence for item in findings)
    return round((weighted / total) * coverage, 3)
