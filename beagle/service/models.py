"""Dataclass views over service records.

These mirror the core data model in design/15 §2 for the entities Phases A and B
need. Stores return these objects; the API serializes them. They are plain data
holders with no behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Organization:
    id: str
    slug: str
    name: str
    created_at: str


@dataclass
class User:
    id: str
    organization_id: str
    username: str
    display_name: str
    email: str
    disabled: bool
    created_at: str


@dataclass
class JwtTokenRecord:
    """Revocation + audit record for a minted token (the JWT ``jti``)."""

    jti: str
    user_id: str
    organization_id: str
    repositories: list[str]
    permissions: list[str]
    issued_at: int
    expires_at: int
    revoked: bool
    label: str
    revoked_at: str | None = None


@dataclass
class Repository:
    id: str
    organization_id: str
    slug: str
    name: str
    remote_url: str | None
    default_branch: str
    storage_path: str
    ingestion_state: str
    created_at: str


@dataclass
class RepositoryAccess:
    id: str
    user_id: str
    repository_id: str
    permissions: list[str]
    granted_at: str


@dataclass
class GitRef:
    repository_id: str
    namespace: str
    ref_name: str
    commit_sha: str
    updated_at: str


@dataclass
class GitIdentity:
    """A name+email seen in Git history, optionally mapped to a verified user.

    The email is the identity anchor (design/15 §5: never map by display-name
    similarity). ``verified_user_id`` is None for unclaimed historical authors.
    """

    organization_id: str
    email: str
    name: str
    verified_user_id: str | None
    verification_method: str | None
    first_seen: int
    last_seen: int
    commit_count: int


@dataclass
class McpSession:
    id: str
    user_id: str
    organization_id: str
    repository_id: str | None
    client_name: str
    client_version: str
    privacy_mode: str
    initial_revision: str | None
    current_revision: str | None
    workspace_id: str | None
    started_at: str
    ended_at: str | None = None


@dataclass
class IndexSnapshot:
    """An immutable per-commit index, keyed by repository + commit (design/15 §8).

    The artifact is a self-contained index of the commit's materialized tree.
    Snapshots are reused across branches that share the commit, and survive a
    force-push because they are keyed by commit, never by branch.
    """

    id: str
    repository_id: str
    commit_sha: str
    tree_sha: str
    indexer_version: str
    status: str
    file_count: int | None
    entity_count: int | None
    observation_count: int | None
    edge_count: int | None
    artifact_path: str
    created_at: str


@dataclass
class ChangeEpisode:
    id: str
    repository_id: str
    title: str
    summary: str
    status: str
    created_by: str
    created_at: str


@dataclass
class Decision:
    id: str
    episode_id: str
    repository_id: str
    problem: str
    goal: str
    decision: str
    rationale: str
    status: str
    created_by: str
    created_at: str


@dataclass
class DecisionActor:
    """A participant in a decision and the role they played.

    ``confirmation_state`` distinguishes inferred attribution from confirmed:
    the authenticated speaker is confirmed; mentioned others stay inferred until
    explicitly confirmed (design/15 §16). Decision roles are never derived from
    Git commit authorship.
    """

    id: str
    decision_id: str
    user_id: str | None
    external_name: str | None
    role: str
    confidence: float
    evidence: str
    confirmation_state: str


@dataclass
class Feedback:
    id: str
    repository_id: str
    episode_id: str | None
    comment: str
    author_user_id: str
    revision: str | None
    entity_id: str | None
    status: str
    rationale: str
    created_at: str


@dataclass
class AuditEvent:
    id: str
    timestamp: str
    user_id: str | None
    organization_id: str | None
    repository_id: str | None
    action: str
    request_id: str | None
    detail: dict = field(default_factory=dict)
