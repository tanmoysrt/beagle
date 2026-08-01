from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import MemoryCfg
from ..index.embeddings import EmbeddingClient
from ..index.vectors import VectorStore
from ..pipeline.models import Finding
from ..storage.db import Database

log = logging.getLogger("beagle.memory")
SEARCH_WIDTH = 40
DISMISSING_ACTIONS = ("false_positive", "dismiss")


@dataclass(frozen=True)
class Match:
    finding_id: str
    similarity: float
    reason: str | None
    author: str | None


class SuppressionMemory:
    """A match needs a high cosine score and the same category."""

    def __init__(
        self,
        core: Database,
        vectors: VectorStore,
        embeddings: EmbeddingClient,
        cfg: MemoryCfg,
    ):
        self.core = core
        self.vectors = vectors
        self.embeddings = embeddings
        self.cfg = cfg

    def remember(self, findings: list[Finding], review_id: str) -> int:
        """Store an embedding per finding so later reviews can match against it."""
        if not findings:
            return 0
        try:
            payloads = [embedding_text(finding) for finding in findings]
            vectors = self.embeddings.embed(payloads)
        except Exception as exc:
            log.warning("could not embed findings for memory: %s", exc)
            return 0
        for finding, vector in zip(findings, vectors):
            self.vectors.upsert_finding(
                finding.identity(review_id), finding.fingerprint, finding.category, vector
            )
        return len(findings)

    def match(self, findings: list[Finding]) -> dict[int, Match]:
        """Best dismissal match per finding, keyed by position in the list."""
        suppressors = self.suppressors()
        if not suppressors or not findings:
            return {}

        matches = self.fingerprint_matches(findings, suppressors)
        pending = [index for index in range(len(findings)) if index not in matches]
        if not pending:
            return matches

        try:
            vectors = self.embeddings.embed([embedding_text(findings[i]) for i in pending])
        except Exception as exc:
            log.warning("suppression matching unavailable: %s", exc)
            return matches

        for index, vector in zip(pending, vectors):
            best = self.best_match(vector, findings[index], suppressors)
            if best is not None:
                matches[index] = best
        return matches

    def fingerprint_matches(
        self, findings: list[Finding], suppressors: dict[str, dict]
    ) -> dict[int, Match]:
        """The same finding seen again is an exact match, no embedding needed."""
        by_fingerprint = {
            record["fingerprint"]: (finding_id, record)
            for finding_id, record in suppressors.items()
            if record.get("fingerprint")
        }
        matches = {}
        for index, finding in enumerate(findings):
            entry = by_fingerprint.get(finding.fingerprint)
            if entry is not None:
                finding_id, record = entry
                matches[index] = Match(finding_id, 1.0, record["reason"], record["author"])
        return matches

    def best_match(self, vector, finding: Finding, suppressors: dict[str, dict]) -> Match | None:
        neighbours = self.vectors.search_findings(vector, k=SEARCH_WIDTH, category=finding.category)
        for finding_id, similarity in neighbours:
            record = suppressors.get(finding_id)
            if record is None:
                continue
            return Match(finding_id, similarity, record["reason"], record["author"])
        return None

    def suppressors(self) -> dict[str, dict]:
        rows = self.core.query(
            "select f.finding_id, f.fingerprint, f.action, f.reason, f.author,"
            " sum(f.weight) as weight from feedback f"
            " where f.action in (?, ?) and f.finding_id is not null"
            " group by f.finding_id",
            DISMISSING_ACTIONS,
        )
        return {
            row["finding_id"]: {
                "fingerprint": row["fingerprint"],
                "action": row["action"],
                "reason": row["reason"],
                "author": row["author"],
                "weight": row["weight"],
            }
            for row in rows
        }

    def threshold_for(self, finding: Finding) -> float:
        return (
            self.cfg.suppress_similarity_security
            if finding.is_security
            else self.cfg.suppress_similarity
        )

    def may_suppress(self, finding: Finding, match: Match) -> bool:
        """Security findings need a reasoned dismissal, not just a high score."""
        if not finding.is_security:
            return True
        return bool(match.reason and match.reason.strip())


def embedding_text(finding: Finding) -> str:
    """Line numbers move between reviews, so they stay out of the match text."""
    return f"{finding.category} in {finding.file}: {finding.title}\n{finding.body[:1200]}"
