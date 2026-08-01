from __future__ import annotations

from dataclasses import dataclass

from ..pipeline.models import Finding
from ..storage.db import Database

MIN_EVENTS = 5
MAX_CORRECTION = 0.5
STRONG_ACTIONS = ("accept", "false_positive")


@dataclass(frozen=True)
class CategoryStats:
    category: str
    accepted: float
    rejected: float

    @property
    def events(self) -> float:
        return self.accepted + self.rejected

    @property
    def false_positive_rate(self) -> float:
        return self.rejected / self.events if self.events else 0.0

    @property
    def correction(self) -> float:
        """Bounded so one bad week cannot zero out a category."""
        if self.events < MIN_EVENTS:
            return 1.0
        return max(1.0 - MAX_CORRECTION, 1.0 - self.false_positive_rate * MAX_CORRECTION * 2)


class Calibrator:
    """Turns accept and dismiss history into a correction on stated confidence."""

    def __init__(self, core: Database):
        self.core = core

    def stats(self) -> dict[str, CategoryStats]:
        rows = self.core.query(
            "select f.category, b.action, sum(b.weight) as weight,"
            " count(distinct coalesce(b.author, b.id)) as voices"
            " from feedback b join findings f on f.id = b.finding_id"
            " where b.action in (?, ?) group by f.category, b.action",
            STRONG_ACTIONS,
        )
        totals: dict[str, list[float]] = {}
        for row in rows:
            bucket = totals.setdefault(row["category"], [0.0, 0.0])
            weighted = float(row["weight"] or 0) * voice_multiplier(row["voices"])
            if row["action"] == "accept":
                bucket[0] += weighted
            else:
                bucket[1] += weighted
        return {
            category: CategoryStats(category, accepted, rejected)
            for category, (accepted, rejected) in totals.items()
        }

    def apply(self, findings: list[Finding]) -> list[Finding]:
        stats = self.stats()
        for finding in findings:
            entry = stats.get(finding.category)
            if entry is None or entry.correction == 1.0:
                continue
            finding.metadata["stated_confidence"] = round(finding.confidence, 3)
            finding.metadata["category_fp_rate"] = round(entry.false_positive_rate, 3)
            finding.confidence = round(finding.confidence * entry.correction, 3)
        return findings

    def report(self) -> list[dict]:
        return [
            {
                "category": entry.category,
                "accepted": round(entry.accepted, 2),
                "rejected": round(entry.rejected, 2),
                "false_positive_rate": round(entry.false_positive_rate, 3),
                "confidence_correction": round(entry.correction, 3),
            }
            for entry in sorted(self.stats().values(), key=lambda item: -item.events)
        ]


def voice_multiplier(voices: int) -> float:
    """Two people saying the same thing outweighs one person saying it twice."""
    return 1.0 + min(voices - 1, 4) * 0.25
