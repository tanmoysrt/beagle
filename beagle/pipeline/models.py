from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import Severity
from ..llm.client import Budget
from ..repo.diff import FileDiff
from .events import EventStream

WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Location:
    file: str
    line_start: int | None = None
    line_end: int | None = None

    def label(self) -> str:
        if self.line_start is None:
            return self.file
        if self.line_end and self.line_end != self.line_start:
            return f"{self.file}:{self.line_start}-{self.line_end}"
        return f"{self.file}:{self.line_start}"


@dataclass
class ReviewUnit:
    key: str
    title: str
    paths: list[str]
    risk_tags: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class Finding:
    file: str
    category: str
    severity: Severity
    title: str
    body: str
    line_start: int | None = None
    line_end: int | None = None
    confidence: float = 0.5
    suggested_patch: str | None = None
    locations: list[Location] = field(default_factory=list)
    context_used: str = ""
    unit: str = ""
    model_severity: Severity | None = None
    app_code: bool | None = None
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.locations:
            self.locations = [Location(self.file, self.line_start, self.line_end)]
        if self.model_severity is None:
            self.model_severity = self.severity

    @property
    def fingerprint(self) -> str:
        """Stable across re-reviews: line numbers move, the issue does not."""
        seed = f"{self.file}|{self.category}|{normalize(self.title)}"
        return hashlib.sha256(seed.encode()).hexdigest()[:32]

    def identity(self, review_id: str) -> str:
        return f"{review_id}:{self.fingerprint[:12]}"

    @property
    def is_security(self) -> bool:
        return self.category == "security"

    def as_row(self, review_id: str, created_at: str) -> tuple:
        return (
            self.identity(review_id),
            review_id,
            self.fingerprint,
            self.file,
            self.line_start,
            self.line_end,
            self.category,
            self.severity.value,
            (self.model_severity or self.severity).value,
            self.confidence,
            None if self.app_code is None else int(self.app_code),
            self.title,
            self.body,
            self.suggested_patch,
            self.context_used,
            json.dumps(
                {
                    **self.metadata,
                    "unit": self.unit,
                    "locations": [asdict(location) for location in self.locations],
                }
            ),
            self.status,
            created_at,
        )

    def to_dict(self, review_id: str = "") -> dict[str, Any]:
        return {
            "id": self.identity(review_id) if review_id else None,
            "fingerprint": self.fingerprint,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "locations": [location.label() for location in self.locations],
            "category": self.category,
            "severity": self.severity.value,
            "model_severity": (self.model_severity or self.severity).value,
            "app_code": self.app_code,
            "confidence": round(self.confidence, 3),
            "title": self.title,
            "body": self.body,
            "suggested_patch": self.suggested_patch,
            "unit": self.unit,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class ReviewSummary:
    verdict: str = "comment"
    description: str = ""
    reasoning: str = ""
    score: int = 5
    confidence: float = 0.0
    coverage: float = 1.0
    attention: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    suppressed: int = 0
    overflow: int = 0
    instruction_files: list[str] = field(default_factory=list)
    skipped_files: list[dict[str, str]] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    reused: int = 0
    duration_seconds: float = 0.0
    degraded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(text: str) -> str:
    return WHITESPACE.sub(" ", text.strip().lower())


def count_by_severity(findings: list[Finding]) -> dict[str, int]:
    counts = {level.value: 0 for level in Severity}
    for finding in findings:
        counts[finding.severity.value] += 1
    return counts


def verdict_for(findings: list[Finding], fail_on: Severity) -> str:
    if any(finding.severity.at_least(fail_on) for finding in findings):
        return "request_changes"
    return "comment" if findings else "approve"


SCORE_FLOOR = {Severity.P0: 1, Severity.P1: 2, Severity.P2: 3, Severity.P3: 4}


def score_for(findings: list[Finding], coverage: float) -> int:
    """How safe this looks, out of 5. The worst finding sets the ceiling."""
    score = min([SCORE_FLOOR.get(item.severity, 5) for item in findings], default=5)
    if sum(1 for item in findings if item.severity is Severity.P2) > 1:
        score = min(score, 3)
    if coverage < 0.8:
        score -= 1
    return max(1, min(5, score))


@dataclass
class ReviewRequest:
    review_id: str
    base: str | None = None
    head: str | None = None
    diff: str | None = None
    author: str | None = None
    index_ref: str | None = None
    fresh: bool = False


@dataclass
class ReviewState:
    """What one review accumulates while it runs.

    Every pass fills part of this and the last one reads all of it, so the
    passes hand over one object instead of a dozen positional arguments.
    """

    request: ReviewRequest
    events: EventStream
    budget: Budget
    started: float = field(default_factory=time.monotonic)
    base_sha: str | None = None
    head_sha: str | None = None
    diffs: list[FileDiff] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    units: list[ReviewUnit] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    contexts: dict[str, str] = field(default_factory=dict)
    instruction_files: list[str] = field(default_factory=list)
    covered: int = 0
    degraded: list[str] = field(default_factory=list)

    @property
    def review_id(self) -> str:
        return self.request.review_id

    @property
    def coverage(self) -> float:
        return (self.covered / len(self.units)) if self.units else 1.0


@dataclass
class ReviewResult:
    review_id: str
    summary: ReviewSummary
    findings: list[Finding] = field(default_factory=list)
    rejected: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    base_sha: str | None = None
    head_sha: str | None = None

    def stored(self) -> list[Finding]:
        """Everything worth keeping a record of, suppressions included."""
        return self.findings + self.suppressed + self.rejected

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "summary": self.summary.to_dict(),
            "findings": [item.to_dict(self.review_id) for item in self.findings],
            "suppressed": [item.to_dict(self.review_id) for item in self.suppressed],
        }
