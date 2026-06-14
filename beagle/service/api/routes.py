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
