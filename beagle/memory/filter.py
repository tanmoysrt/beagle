from __future__ import annotations

from dataclasses import dataclass, field

from ..config import MemoryCfg
from ..pipeline.models import Finding
from .calibration import Calibrator
from .rules import RuleStore
from .suppression import SuppressionMemory


@dataclass
class MemoryOutcome:
    kept: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    downranked: list[Finding] = field(default_factory=list)


class MemoryFilter:
    """Applies what the team has taught Beagle to a fresh set of findings."""

    def __init__(
        self,
        cfg: MemoryCfg,
        suppression: SuppressionMemory | None = None,
        calibrator: Calibrator | None = None,
        rules: RuleStore | None = None,
    ):
        self.cfg = cfg
        self.suppression = suppression
        self.calibrator = calibrator
        self.rules = rules

    def filter(self, findings: list[Finding]) -> MemoryOutcome:
        outcome = MemoryOutcome(kept=list(findings))
        if self.suppression is not None and findings:
            outcome = self.apply_suppression(findings)
        if self.calibrator is not None:
            self.calibrator.apply(outcome.kept)
        return outcome

    def apply_suppression(self, findings: list[Finding]) -> MemoryOutcome:
        matches = self.suppression.match(findings)
        outcome = MemoryOutcome()
        for index, finding in enumerate(findings):
            match = matches.get(index)
            if match is None:
                outcome.kept.append(finding)
                continue
            threshold = self.suppression.threshold_for(finding)
            if match.similarity >= threshold and self.suppression.may_suppress(finding, match):
                self.mark(finding, match, "suppressed")
                outcome.suppressed.append(finding)
            elif match.similarity >= self.cfg.downrank_similarity:
                self.mark(finding, match, "downranked")
                finding.confidence = round(finding.confidence * 0.6, 3)
                outcome.kept.append(finding)
                outcome.downranked.append(finding)
            else:
                outcome.kept.append(finding)
        return outcome

    def mark(self, finding: Finding, match, status: str) -> None:
        finding.status = status
        finding.metadata["memory"] = {
            "status": status,
            "matched_finding": match.finding_id,
            "similarity": round(match.similarity, 4),
            "dismissed_by": match.author,
            "reason": match.reason,
        }

    def remember(self, findings: list[Finding], review_id: str) -> int:
        if self.suppression is None:
            return 0
        return self.suppression.remember(findings, review_id)

    def conventions_block(self) -> str:
        return self.rules.block() if self.rules is not None else ""
