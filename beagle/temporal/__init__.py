"""Temporal decision and change memory (design/13).

Records why code changed — problem, decision, rationale, rejected alternatives,
and the deterministic diff facts that connect a change episode to commits and
entities. Deterministic facts (commits, entity changes, changesets) stay
separate from generated summaries (episodes, decisions) and raw provenance
(sessions); the engine never invents rationale.
"""

from __future__ import annotations

from beagle.temporal.changes import ChangeAnalyzer, entity_fingerprint, parse_diff
from beagle.temporal.git import Git, GitError
from beagle.temporal.models import (
    Alternative, ChangeEpisode, ChangeReport, ChangeSet, CommitRecord, Decision,
    EntityChange, FollowUp, Session,
)
from beagle.temporal.notes import GitNotes
from beagle.temporal.repository import TemporalRepository
from beagle.temporal.service import TemporalService

__all__ = [
    "ChangeAnalyzer", "parse_diff", "entity_fingerprint",
    "Git", "GitError", "GitNotes",
    "TemporalRepository", "TemporalService",
    "ChangeEpisode", "ChangeReport", "ChangeSet", "CommitRecord", "Decision",
    "Alternative", "EntityChange", "FollowUp", "Session",
]
