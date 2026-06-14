"""JSON routes: identity, repositories, sessions (design/15 §21).

Every route authenticates through the bearer dependency, enforces the required
permission and repository scope, and records an audit event. Responses carry the
authenticated user and (where relevant) the repository and its index status.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from beagle.service import permissions
from beagle.service.api.context import authenticate, container_of, request_id
from beagle.service.jwt_service import AuthenticatedIdentity

router = APIRouter(prefix="/v1")


class RegisterRepositoryRequest(BaseModel):
    slug: str
    name: str
    remote_url: str | None = None
    default_branch: str = "main"


class OpenSessionRequest(BaseModel):
    repository_id: str | None = None
    client_name: str = ""
    client_version: str = ""
    privacy_mode: str = "summary"
    initial_revision: str | None = None


class MapIdentityRequest(BaseModel):
    email: str
    user_id: str
    method: str = "admin"


class ClaimIdentityRequest(BaseModel):
    email: str


class EpisodeRequest(BaseModel):
    title: str
    summary: str = ""


class DecisionRequest(BaseModel):
    decision: str
    problem: str = ""
    goal: str = ""
    rationale: str = ""


class ActorRequest(BaseModel):
    role: str
    user_id: str | None = None
    external_name: str | None = None
    confidence: float = 1.0
    evidence: str = ""
    confirmation_state: str = "inferred"


class FeedbackRequest(BaseModel):
    comment: str
    episode_id: str | None = None
    revision: str | None = None
    entity_id: str | None = None
    rationale: str = ""


class StatusRequest(BaseModel):
    status: str


class SummaryRequest(BaseModel):
    summary: str
    problem: str = ""
    decision: str = ""


@router.get("/me")
def current_user(
    request: Request, identity: AuthenticatedIdentity = Depends(authenticate)
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        user = container.identity.get_user(conn, identity.user_id)
        access = container.identity.list_access(conn, identity.user_id)
    return {
        "user": asdict(user),
        "repositories": identity.repositories,
        "permissions": identity.permissions,
        "access": [asdict(a) for a in access],
    }


@router.post("/repositories")
def register_repository(
    request: Request,
    body: RegisterRepositoryRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    permissions.require_permission(identity.permissions, permissions.REPO_REGISTER)
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repository_service.register(
            conn, identity.organization_id, body.slug, body.name,
            body.remote_url, body.default_branch,
        )
        container.audit.record(
            conn, "repo.register", identity.user_id, identity.organization_id,
            repo.id, request_id(request), {"slug": body.slug},
        )
    return {"user": identity.user_id, "repository": asdict(repo)}


@router.get("/repositories")
def list_repositories(
    request: Request, identity: AuthenticatedIdentity = Depends(authenticate)
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        repos = container.repositories.list_for_org(conn, identity.organization_id)
    return {"user": identity.user_id, "repositories": [asdict(r) for r in repos]}


@router.get("/repositories/{repository_id}")
def repository_status(
    request: Request,
    repository_id: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
        permissions.require_repository(identity.repositories, repo.slug)
        status = container.repository_service.status(conn, repository_id)
    return {"user": identity.user_id, "repository": asdict(repo), "index_status": asdict(status)}


@router.post("/repositories/{repository_id}/sync")
def sync_repository(
    request: Request,
    repository_id: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    permissions.require_permission(identity.permissions, permissions.REPO_SYNC)
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
        permissions.require_repository(identity.repositories, repo.slug)
        result = container.repository_service.sync(conn, repository_id)
        container.audit.record(
            conn, "repo.sync", identity.user_id, identity.organization_id,
            repository_id, request_id(request), {"refs": result.ref_count},
        )
    return {"user": identity.user_id, "index_status": asdict(result)}


@router.get("/repositories/{repository_id}/commits")
def commit_history(
    request: Request,
    repository_id: str,
    limit: int = 50,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
        permissions.require_repository(identity.repositories, repo.slug)
        permissions.require_permission(identity.permissions, permissions.SOURCE_READ)
        commits = container.commits.history(conn, repository_id, limit=min(limit, 200))
    return {"user": identity.user_id, "repository_id": repository_id, "commits": commits}


@router.get("/repositories/{repository_id}/commits/search")
def search_commit_messages(
    request: Request,
    repository_id: str,
    q: str,
    limit: int = 20,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
        permissions.require_repository(identity.repositories, repo.slug)
        permissions.require_permission(identity.permissions, permissions.SOURCE_READ)
        commits = container.commits.search(conn, repository_id, q, limit=min(limit, 100))
    return {"user": identity.user_id, "query": q, "commits": commits}


@router.get("/repositories/{repository_id}/commits/{sha}")
def commit_detail(
    request: Request,
    repository_id: str,
    sha: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
        permissions.require_repository(identity.repositories, repo.slug)
        permissions.require_permission(identity.permissions, permissions.SOURCE_READ)
        commit = container.commits.get_commit(conn, repository_id, sha)
    return {"user": identity.user_id, "commit": commit}


def _authorize_repo(container, identity, repository_id, permission):
    """Return the repository after checking scope + permission; raises on failure."""
    with container.database.connect() as conn:
        repo = container.repositories.get(conn, repository_id)
    permissions.require_repository(identity.repositories, repo.slug)
    permissions.require_permission(identity.permissions, permission)
    return repo


def _repo_slug(container, conn, repository_id):
    return container.repositories.get(conn, repository_id).slug


@router.get("/repositories/{repository_id}/sync-status")
def sync_status(
    request: Request,
    repository_id: str,
    head: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    """Tell the bridge whether the service already has a commit and its snapshot."""
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    has_commit = container.mirror.has_commit(repository_id, head)
    has_snapshot = False
    with container.database.connect() as conn:
        snapshot = container.snapshots.find(conn, repository_id, head)
        has_snapshot = bool(snapshot and snapshot.status == "ready")
    return {
        "user": identity.user_id,
        "repository_id": repository_id,
        "head": head,
        "has_commit": has_commit,
        "has_snapshot": has_snapshot,
    }


@router.post("/repositories/{repository_id}/revisions/{revision}/index")
def index_revision(
    request: Request,
    repository_id: str,
    revision: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.REPO_SYNC)
    snapshot = container.revision_indexer.index_revision(repository_id, revision)
    with container.database.connect() as conn:
        container.audit.record(
            conn, "revision.index", identity.user_id, identity.organization_id,
            repository_id, request_id(request), {"commit": snapshot.commit_sha},
        )
    return {"user": identity.user_id, "snapshot": asdict(snapshot)}


@router.get("/repositories/{repository_id}/snapshots")
def list_snapshots(
    request: Request,
    repository_id: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    with container.database.connect() as conn:
        snapshots = container.snapshots.list_for_repository(conn, repository_id)
    return {"user": identity.user_id, "snapshots": [asdict(s) for s in snapshots]}


@router.get("/repositories/{repository_id}/revisions/{revision}")
def revision_snapshot(
    request: Request,
    repository_id: str,
    revision: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    sha = container.mirror.resolve(repository_id, revision)
    with container.database.connect() as conn:
        snapshot = container.snapshots.get(conn, repository_id, sha or revision)
    return {"user": identity.user_id, "snapshot": asdict(snapshot)}


@router.get("/repositories/{repository_id}/revisions/{revision}/search")
def search_revision(
    request: Request,
    repository_id: str,
    revision: str,
    q: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    from beagle.service.revision_indexer import search_snapshot_entities

    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    sha = container.mirror.resolve(repository_id, revision)
    with container.database.connect() as conn:
        snapshot = container.snapshots.get(conn, repository_id, sha or revision)
    results = search_snapshot_entities(snapshot.artifact_path, q, limit=20)
    return {
        "user": identity.user_id,
        "repository": repository_id,
        "revision": snapshot.commit_sha,
        "results": results,
    }


@router.get("/repositories/{repository_id}/compare")
def compare_revisions(
    request: Request,
    repository_id: str,
    base: str,
    head: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    result = container.revision_comparer.compare(repository_id, base, head)
    return {"user": identity.user_id, "comparison": asdict(result)}


@router.get("/repositories/{repository_id}/compare-branches")
def compare_branches(
    request: Request,
    repository_id: str,
    target: str,
    source: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    result = container.revision_comparer.branch_compare(repository_id, target, source)
    return {"user": identity.user_id, "comparison": asdict(result)}


@router.get("/repositories/{repository_id}/merge-summary/{revision}")
def merge_summary(
    request: Request,
    repository_id: str,
    revision: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    result = container.revision_comparer.merge_summary(repository_id, revision)
    return {"user": identity.user_id, "comparison": asdict(result)}


@router.post("/repositories/{repository_id}/episodes")
def create_episode(
    request: Request,
    repository_id: str,
    body: EpisodeRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.DECISION_WRITE)
    with container.database.connect() as conn:
        episode = container.decisions.create_episode(
            conn, repository_id, body.title, body.summary, identity.user_id
        )
    return {"user": identity.user_id, "episode": asdict(episode)}


@router.post("/episodes/{episode_id}/decisions")
def record_decision(
    request: Request,
    episode_id: str,
    body: DecisionRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    permissions.require_permission(identity.permissions, permissions.DECISION_WRITE)
    with container.database.connect() as conn:
        episode = container.decisions.get_episode(conn, episode_id)
        permissions.require_repository(
            identity.repositories, _repo_slug(container, conn, episode.repository_id)
        )
        decision = container.decisions.record_decision(
            conn, episode_id, episode.repository_id, body.decision, identity.user_id,
            body.problem, body.goal, body.rationale,
        )
    return {"user": identity.user_id, "decision": asdict(decision)}


@router.post("/decisions/{decision_id}/actors")
def add_decision_actor(
    request: Request,
    decision_id: str,
    body: ActorRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    permissions.require_permission(identity.permissions, permissions.DECISION_WRITE)
    with container.database.connect() as conn:
        actor = container.decisions.add_actor(
            conn, decision_id, body.role, body.user_id, body.external_name,
            body.confidence, body.evidence, body.confirmation_state,
        )
    return {"user": identity.user_id, "actor": asdict(actor)}


@router.post("/decisions/{decision_id}/actors/{actor_id}/confirm")
def confirm_decision_actor(
    request: Request,
    decision_id: str,
    actor_id: str,
    body: StatusRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    permissions.require_permission(identity.permissions, permissions.DECISION_WRITE)
    with container.database.connect() as conn:
        container.decisions.confirm_actor(conn, actor_id, body.status)
    return {"user": identity.user_id, "actor_id": actor_id, "confirmation_state": body.status}


@router.get("/repositories/{repository_id}/decisions")
def decision_history(
    request: Request,
    repository_id: str,
    entity: str | None = None,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.DECISION_READ)
    with container.database.connect() as conn:
        decisions = container.decisions.list_decisions(conn, repository_id, entity)
    return {"user": identity.user_id, "decisions": decisions}


@router.post("/repositories/{repository_id}/feedback")
def record_feedback(
    request: Request,
    repository_id: str,
    body: FeedbackRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.FEEDBACK_WRITE)
    with container.database.connect() as conn:
        item = container.feedback.record(
            conn, repository_id, body.comment, identity.user_id, body.episode_id,
            body.revision, body.entity_id, body.rationale,
        )
    return {"user": identity.user_id, "feedback": asdict(item)}


@router.post("/feedback/{feedback_id}/status")
def set_feedback_status(
    request: Request,
    feedback_id: str,
    body: StatusRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    permissions.require_permission(identity.permissions, permissions.FEEDBACK_WRITE)
    with container.database.connect() as conn:
        container.feedback.set_status(conn, feedback_id, body.status)
    return {"user": identity.user_id, "feedback_id": feedback_id, "status": body.status}


@router.get("/repositories/{repository_id}/feedback")
def feedback_history(
    request: Request,
    repository_id: str,
    entity: str | None = None,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.FEEDBACK_READ)
    with container.database.connect() as conn:
        items = container.feedback.history(conn, repository_id, entity)
    return {"user": identity.user_id, "feedback": [asdict(i) for i in items]}


@router.post("/sessions/{session_id}/summary")
def store_session_summary(
    request: Request,
    session_id: str,
    body: SummaryRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        session = container.sessions.get_session(conn, session_id)
        if session.user_id != identity.user_id:
            permissions.require_permission(identity.permissions, permissions.ADMIN_IDENTITY)
        summary_id = container.sessions.store_summary(
            conn, session_id, body.summary, body.problem, body.decision
        )
    return {"user": identity.user_id, "summary_id": summary_id}


@router.post("/repositories/{repository_id}/revisions/{revision}/dependencies")
def analyze_dependencies(
    request: Request,
    repository_id: str,
    revision: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.REPO_SYNC)
    result = container.dependency_service.analyze_revision(repository_id, revision)
    return {"user": identity.user_id, "dependencies": asdict(result)}


@router.get("/repositories/{repository_id}/revisions/{revision}/dependencies")
def get_dependencies(
    request: Request,
    repository_id: str,
    revision: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    sha = container.mirror.resolve(repository_id, revision)
    with container.database.connect() as conn:
        snapshot = container.dependencies.get_snapshot(conn, repository_id, sha or revision)
    return {"user": identity.user_id, "snapshot": snapshot}


@router.get("/repositories/{repository_id}/dependencies/search")
def search_dependencies(
    request: Request,
    repository_id: str,
    q: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    _authorize_repo(container, identity, repository_id, permissions.SOURCE_READ)
    with container.database.connect() as conn:
        packages = container.dependencies.search_packages(conn, repository_id, q)
    return {"user": identity.user_id, "packages": packages}


@router.get("/identities")
def list_git_identities(
    request: Request, identity: AuthenticatedIdentity = Depends(authenticate)
) -> dict:
    permissions.require_permission(identity.permissions, permissions.ADMIN_IDENTITY)
    container = container_of(request)
    with container.database.connect() as conn:
        rows = container.git_identities.list_identities(conn, identity.organization_id)
    return {"user": identity.user_id, "identities": [asdict(r) for r in rows]}


@router.get("/me/identities")
def my_git_identities(
    request: Request, identity: AuthenticatedIdentity = Depends(authenticate)
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        rows = container.git_identities.list_for_user(
            conn, identity.organization_id, identity.user_id
        )
    return {"user": identity.user_id, "identities": [asdict(r) for r in rows]}


@router.post("/identities/map")
def map_git_identity(
    request: Request,
    body: MapIdentityRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    permissions.require_permission(identity.permissions, permissions.ADMIN_IDENTITY)
    container = container_of(request)
    with container.database.connect() as conn:
        mapped = container.git_identities.map_identity(
            conn, identity.organization_id, body.email, body.user_id, body.method
        )
        container.audit.record(
            conn, "identity.map", identity.user_id, identity.organization_id,
            None, request_id(request), {"email": body.email, "user": body.user_id},
        )
    return {"user": identity.user_id, "identity": asdict(mapped)}


@router.post("/identities/claim")
def claim_git_identity(
    request: Request,
    body: ClaimIdentityRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        existing = container.git_identities.get(conn, identity.organization_id, body.email)
        if existing.verified_user_id and existing.verified_user_id != identity.user_id:
            permissions.require_permission(identity.permissions, permissions.ADMIN_IDENTITY)
        mapped = container.git_identities.map_identity(
            conn, identity.organization_id, body.email, identity.user_id, "claim"
        )
        container.audit.record(
            conn, "identity.claim", identity.user_id, identity.organization_id,
            None, request_id(request), {"email": body.email},
        )
    return {"user": identity.user_id, "identity": asdict(mapped)}


@router.post("/sessions")
def open_session(
    request: Request,
    body: OpenSessionRequest,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        session = container.sessions.open_session(
            conn, identity.user_id, identity.organization_id, body.repository_id,
            body.client_name, body.client_version, body.privacy_mode, body.initial_revision,
        )
        container.audit.record(
            conn, "session.open", identity.user_id, identity.organization_id,
            body.repository_id, request_id(request), {"session": session.id},
        )
    return {"user": identity.user_id, "session": asdict(session)}


@router.post("/sessions/{session_id}/end")
def end_session(
    request: Request,
    session_id: str,
    identity: AuthenticatedIdentity = Depends(authenticate),
) -> dict:
    container = container_of(request)
    with container.database.connect() as conn:
        session = container.sessions.get_session(conn, session_id)
        if session.user_id != identity.user_id:
            permissions.require_permission(identity.permissions, permissions.ADMIN_IDENTITY)
        container.sessions.close_session(conn, session_id)
    return {"user": identity.user_id, "session_id": session_id, "ended": True}
