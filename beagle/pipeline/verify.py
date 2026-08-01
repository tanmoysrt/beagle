from __future__ import annotations

from ..config import Severity
from ..llm.client import Budget, LLMClient
from ..prompts.loader import PromptSet, verify_values
from .models import Finding
from .review import clamp, coerce_severity
from .schemas import OUTPUT_INSTRUCTIONS, VERIFY_SCHEMA

SHAKY_CONFIDENCE = 0.75


class Verifier:
    """Re-checks the findings that would cost the most trust if wrong.

    Every security finding is verified regardless of confidence, along with
    any P0 or P1 the reviewer was not sure about.
    """

    def __init__(self, client: LLMClient, prompts: PromptSet):
        self.client = client
        self.prompts = prompts

    def needs_check(self, finding: Finding) -> bool:
        if finding.metadata.get("detector") == "secret_scan":
            return False  # deterministic match, nothing for a model to confirm
        if finding.is_security:
            return True
        return finding.severity.at_least(Severity.P1) and finding.confidence < SHAKY_CONFIDENCE

    def verify_all(
        self,
        findings: list[Finding],
        contexts: dict[str, str],
        review_id: str,
        budget: Budget | None = None,
    ) -> tuple[list[Finding], list[Finding]]:
        kept, rejected = [], []
        prompt = self.prompts.get("verify").render(verify_values(OUTPUT_INSTRUCTIONS["verify"]))
        for finding in findings:
            if not self.needs_check(finding):
                kept.append(finding)
                continue
            system = self.system_for(prompt, contexts.get(finding.unit, ""))
            verdict = self.check(finding, system, review_id, budget)
            if not isinstance(verdict, dict):
                kept.append(finding)
            elif verdict.get("verdict") == "reject":
                finding.status = "rejected"
                finding.metadata["reject_reason"] = verdict.get("reason", "")
                rejected.append(finding)
            else:
                kept.append(self.revise(finding, verdict))
        return kept, rejected

    def system_for(self, prompt: str, context: str) -> list[dict]:
        """Context goes in the cached prefix so a unit's findings share one read."""
        blocks: list[dict] = [{"type": "text", "text": prompt}]
        if context:
            blocks.append(
                {
                    "type": "text",
                    "text": f"THE CONTEXT THE REVIEWER SAW\n\n{context}",
                    "cache_control": {"type": "ephemeral"},
                }
            )
        return blocks

    def check(
        self,
        finding: Finding,
        system: list[dict],
        review_id: str,
        budget: Budget | None,
    ) -> dict | None:
        try:
            reply = self.client.structured(
                tier="opus",
                system=system,
                user=self.question(finding),
                schema=VERIFY_SCHEMA,
                tool_name="verify_finding",
                max_tokens=2000,
                prompt_name="verify",
                review_id=review_id,
                unit=finding.unit,
                budget=budget,
            )
            return reply.data
        except Exception:
            return None  # a failed check leaves the finding as the reviewer left it

    def question(self, finding: Finding) -> str:
        locations = ", ".join(location.label() for location in finding.locations)
        return (
            f"FINDING UNDER REVIEW\n"
            f"severity: {finding.severity.value}\ncategory: {finding.category}\n"
            f"locations: {locations}\nreviewer confidence: {finding.confidence:.2f}\n"
            f"title: {finding.title}\n\n{finding.body}"
        )

    def revise(self, finding: Finding, verdict: dict) -> Finding:
        finding.metadata["verified"] = verdict.get("verdict", "confirm")
        if verdict.get("verdict") == "revise":
            if verdict.get("severity"):
                finding.severity = coerce_severity(verdict["severity"])
            if verdict.get("body"):
                finding.body = verdict["body"].strip()
        if verdict.get("confidence") is not None:
            finding.confidence = clamp(verdict["confidence"])
        elif verdict.get("verdict") == "confirm":
            finding.confidence = min(1.0, finding.confidence + 0.1)
        return finding
