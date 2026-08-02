from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Severity
from ..pipeline.events import EventStream
from ..pipeline.models import Finding
from ..pipeline.runner import ReviewRequest


@dataclass
class Expectation:
    file: str
    pattern: str
    category: str | None = None
    severity: str | None = None

    def matches(self, finding: Finding) -> bool:
        if self.file and self.file != finding.file:
            return False
        if self.category and self.category != finding.category:
            return False
        text = f"{finding.title}\n{finding.body}"
        return bool(re.search(self.pattern, text, re.I))


@dataclass
class Case:
    id: str
    diff: str
    expect: list[Expectation] = field(default_factory=list)
    forbid: list[Expectation] = field(default_factory=list)
    max_findings: int | None = None


@dataclass
class CaseResult:
    id: str
    found: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)
    severity_errors: list[str] = field(default_factory=list)
    extra: int = 0
    cost_usd: float = 0.0
    degraded: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.missed or self.forbidden_hits or self.severity_errors)


@dataclass
class EvalReport:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def recall(self) -> float:
        hit = sum(len(case.found) for case in self.cases)
        total = hit + sum(len(case.missed) for case in self.cases)
        return hit / total if total else 1.0

    @property
    def noise(self) -> float:
        """Findings beyond what the case expected, per case."""
        return sum(case.extra for case in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def cost_usd(self) -> float:
        return round(sum(case.cost_usd for case in self.cases), 4)

    @property
    def degraded(self) -> list[str]:
        """A case the reviewer could not finish scores nothing and means nothing.

        Without this a broken key or a provider outage reads as a model that
        found no defects.
        """
        return sorted({note for case in self.cases for note in case.degraded})

    def to_dict(self) -> dict:
        return {
            "cases": len(self.cases),
            "passed": sum(1 for case in self.cases if case.passed),
            "recall": round(self.recall, 3),
            "false_positives": sum(len(case.forbidden_hits) for case in self.cases),
            "severity_errors": sum(len(case.severity_errors) for case in self.cases),
            "extra_findings_per_case": round(self.noise, 2),
            "cost_usd": self.cost_usd,
            "degraded_cases": sum(1 for case in self.cases if case.degraded),
            "degraded": self.degraded[:10],
            "detail": [
                {
                    "id": case.id,
                    "passed": case.passed,
                    "found": case.found,
                    "missed": case.missed,
                    "forbidden_hits": case.forbidden_hits,
                    "severity_errors": case.severity_errors,
                    "extra": case.extra,
                }
                for case in self.cases
            ],
        }


class EvalHarness:
    """Scores Beagle against a golden set."""

    def __init__(self, service):
        self.service = service

    def run(self, cases: list[Case]) -> EvalReport:
        report = EvalReport()
        for case in cases:
            report.cases.append(self.run_case(case))
        return report

    def run_case(self, case: Case) -> CaseResult:
        # An eval measures the model, never the stored answer: the review id
        # repeats on every run, so reuse would score the first run twice.
        request = ReviewRequest(review_id=f"eval-{case.id}", diff=case.diff, fresh=True)
        result = self.service.runner().run(request, EventStream())
        outcome = CaseResult(
            id=case.id,
            cost_usd=result.summary.cost_usd,
            degraded=list(result.summary.degraded),
        )
        matched: set[int] = set()

        for expectation in case.expect:
            hit = next(
                (
                    index
                    for index, finding in enumerate(result.findings)
                    if index not in matched and expectation.matches(finding)
                ),
                None,
            )
            if hit is None:
                outcome.missed.append(f"{expectation.file}: /{expectation.pattern}/")
                continue
            matched.add(hit)
            finding = result.findings[hit]
            outcome.found.append(f"{finding.file}: {finding.title}")
            if expectation.severity and finding.severity is not Severity(expectation.severity):
                outcome.severity_errors.append(
                    f"{finding.title}: expected {expectation.severity}, got {finding.severity.value}"
                )

        for expectation in case.forbid:
            for finding in result.findings:
                if expectation.matches(finding):
                    outcome.forbidden_hits.append(f"{finding.file}: {finding.title}")

        outcome.extra = max(0, len(result.findings) - len(case.expect))
        return outcome


def load_cases(path: Path | str) -> list[Case]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(path).parent
    cases = []
    for raw in data["cases"]:
        diff = raw.get("diff") or (base / raw["diff_file"]).read_text(encoding="utf-8")
        cases.append(
            Case(
                id=raw["id"],
                diff=diff,
                expect=[Expectation(**item) for item in raw.get("expect", [])],
                forbid=[Expectation(**item) for item in raw.get("forbid", [])],
                max_findings=raw.get("max_findings"),
            )
        )
    return cases
