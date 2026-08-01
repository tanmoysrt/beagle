from __future__ import annotations

import re
from dataclasses import dataclass

from ..storage.dao import IndexStore
from .models import ReviewUnit

BLAST_RADIUS_CALLERS = 8
REACH_DEPTH = 2

SENSITIVE = {
    "auth": r"auth|login|signin|permission|authoriz|access_control|rbac|acl",
    "session": r"session|cookie|jwt|refresh_token|bearer",
    "crypto": r"crypt|cipher|hash|hmac|signature|nonce|salt|pbkdf|bcrypt|argon",
    "payments": r"payment|charge|refund|invoice|billing|subscription|stripe|checkout",
    "data_loss": r"\bdelete|\bdrop_|truncate|purge|wipe|destroy",
    "concurrency": r"thread|lock|mutex|semaphore|async|await|goroutine|concurren|atomic",
}
PATTERNS = {tag: re.compile(pattern, re.I) for tag, pattern in SENSITIVE.items()}


@dataclass(frozen=True)
class RiskReport:
    tags: list[str]
    reached: int
    evidence: dict[str, str]


class RiskTagger:
    """Tags a unit from the index rather than asking a model."""

    def __init__(self, store: IndexStore):
        self.store = store

    def tag(self, unit: ReviewUnit) -> RiskReport:
        names, reached = self.reach(unit.paths)
        evidence: dict[str, str] = {}
        # the change itself is better evidence than something two hops away
        ordered = list(unit.paths) + sorted(names - set(unit.paths))

        for tag, pattern in PATTERNS.items():
            hit = next((name for name in ordered if pattern.search(name)), None)
            if hit:
                evidence[tag] = hit

        if reached >= BLAST_RADIUS_CALLERS:
            evidence["blast_radius"] = f"{reached} symbols depend on this change"

        return RiskReport(sorted(evidence), reached, evidence)

    def reach(self, paths: list[str]) -> tuple[set[str], int]:
        """Names within a couple of call-graph hops of the change."""
        names: set[str] = set(paths)
        frontier: list[dict] = []
        for path in paths:
            frontier.extend(self.store.symbols_in_file(path))
            names.update(symbol["qualified_name"] for symbol in frontier)

        seen = {symbol["id"] for symbol in frontier}
        reached = 0
        for _ in range(REACH_DEPTH):
            following: list[dict] = []
            for symbol in frontier:
                for neighbour in self.store.callers_of(symbol["id"]):
                    reached += 1
                    if neighbour["id"] in seen:
                        continue
                    seen.add(neighbour["id"])
                    names.add(neighbour["qualified_name"])
                    names.add(neighbour["path"])
                    following.append(neighbour)
                for neighbour in self.store.callees_of(symbol["id"]):
                    name = neighbour.get("qualified_name") or neighbour.get("dst_name")
                    if name:
                        names.add(name)
                    if neighbour.get("id") and neighbour["id"] not in seen:
                        seen.add(neighbour["id"])
                        following.append(neighbour)
            frontier = following
            if not frontier:
                break
        return names, reached

    def apply(self, units: list[ReviewUnit]) -> list[ReviewUnit]:
        for unit in units:
            report = self.tag(unit)
            merged = sorted(set(unit.risk_tags) | set(report.tags))
            unit.risk_tags = merged
            if report.evidence:
                unit.rationale = (unit.rationale + " " if unit.rationale else "") + (
                    "risk: " + "; ".join(f"{tag} ({why})" for tag, why in report.evidence.items())
                )
        return units
