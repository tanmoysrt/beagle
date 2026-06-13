"""Plain records for the temporal decision and change memory (design/13).

Three kinds of information are kept separate, as the design demands:
deterministic code facts (``CommitRecord``, ``EntityChange``, ``ChangeSet``),
generated decision summaries (``ChangeEpisode``, ``Decision``, ``Alternative``,
``FollowUp``), and raw conversation provenance (``Session``, ``Provenance``).
These are dumb containers; behaviour lives in the service and repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# --- deterministic code facts -----------------------------------------------

CHANGE_TYPES = (
    "added", "removed", "modified", "renamed", "moved",
    "signature_changed", "behavior_changed", "relationship_changed", "unknown",
)


@dataclass
class EntityChange:
    """One entity touched by a change, with its before/after identity."""

    change_type: str
    entity_before: Optional[str] = None
    entity_after: Optional[str] = None
    path_before: Optional[str] = None
    path_after: Optional[str] = None
    diff_ranges: list[tuple[int, int]] = field(default_factory=list)
    confidence: float = 1.0
    episode_id: Optional[str] = None
    commit_sha: Optional[str] = None
    id: Optional[int] = None


@dataclass
class CommitRecord:
    """A commit's deterministic metadata plus its normalized patch id."""

    commit_sha: str
    parent_shas: list[str] = field(default_factory=list)
    message: str = ""
    author: str = ""
    timestamp: float = 0.0
    patch_id: Optional[str] = None
    episode_id: Optional[str] = None
    match_confidence: float = 1.0


@dataclass
class ChangeSet:
    """A base..head diff identified by patch id and entity fingerprint."""

    id: str
    base_commit: Optional[str]
    head_commit: Optional[str]
    patch_id: Optional[str] = None
    entity_fingerprint: Optional[str] = None
    summary: str = ""
    episode_id: Optional[str] = None


@dataclass
class ChangeReport:
    """Result of analyzing a working tree or commit range — facts only."""

    base_commit: Optional[str]
    head_commit: Optional[str]
    commits: list[CommitRecord] = field(default_factory=list)
    entity_changes: list[EntityChange] = field(default_factory=list)
    changeset: Optional[ChangeSet] = None
    notes: list[str] = field(default_factory=list)


# --- generated summaries -----------------------------------------------------

EPISODE_STATUSES = ("draft", "active", "implemented", "abandoned", "superseded")
DECISION_STATUSES = ("proposed", "accepted", "rejected", "superseded", "unknown")
CONFIRMATION_STATES = ("generated", "reviewed", "edited", "confirmed")


@dataclass
class ChangeEpisode:
    id: str
    title: str
    status: str = "draft"
    created_at: float = 0.0
    updated_at: float = 0.0
    base_commit: Optional[str] = None
    head_commit: Optional[str] = None
    branch: Optional[str] = None
    summary: Optional[str] = None
    problem: Optional[str] = None
    goal: Optional[str] = None
    outcome: Optional[str] = None
    confidence: Optional[float] = None
    confirmation: str = "generated"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    id: str
    episode_id: str
    statement: str
    status: str = "proposed"
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    created_at: float = 0.0
    superseded_by: Optional[str] = None
    confirmation: str = "generated"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Alternative:
    id: str
    episode_id: str
    description: str
    status: str = "rejected"
    rejection_reason: Optional[str] = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class FollowUp:
    id: str
    episode_id: str
    description: str
    status: str = "open"
    priority: str = "normal"
    related_entities: list[str] = field(default_factory=list)


# --- provenance --------------------------------------------------------------

@dataclass
class Session:
    id: str
    episode_id: Optional[str] = None
    tool: Optional[str] = None
    started_at: float = 0.0
    ended_at: Optional[float] = None
    working_directory: Optional[str] = None
    start_commit: Optional[str] = None
    end_commit: Optional[str] = None
    transcript_path: Optional[str] = None
    transcript_hash: Optional[str] = None
    summary: Optional[str] = None
    redaction_status: Optional[str] = None
