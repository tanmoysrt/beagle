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
class AuditEvent:
    id: str
    timestamp: str
    user_id: str | None
    organization_id: str | None
    repository_id: str | None
    action: str
    request_id: str | None
    detail: dict = field(default_factory=dict)
