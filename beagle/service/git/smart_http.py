"""Authenticated Git Smart HTTP (design/15 §6, §21).

Git objects move over Git's own protocol, not JSON. This handler authenticates
the JWT, authorizes the requested service against the repository scope, then
delegates the transport to ``git http-backend`` (CGI). Push scoping to a user's
own namespace is additionally enforced by the per-repo ``pre-receive`` hook.

The service is intentionally minimal — only fetch, push of missing objects, and
workspace refs — not a full Git hosting product.
"""

from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass, field

from beagle.service.config import ServiceConfig
from beagle.service.db import Database
from beagle.service.errors import AuthenticationError, PermissionDenied, ServiceError
from beagle.service.jwt_service import AuthenticatedIdentity, JwtService
from beagle.service import permissions
from beagle.service.repositories import RepositoryStore

_UPLOAD_PACK = "git-upload-pack"
_RECEIVE_PACK = "git-receive-pack"
# Receiving a pack is a write; either scope can legitimately push (missing
# commits under repo:sync, workspace refs under workspace:create).
_RECEIVE_PERMISSIONS = (permissions.REPO_SYNC, permissions.WORKSPACE_CREATE)


@dataclass
class GitHttpResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


def authorize_git_service(
    identity: AuthenticatedIdentity, repository_slug: str, git_service: str
) -> None:
    """Raise unless the identity may run ``git_service`` on the repository."""
    permissions.require_repository(identity.repositories, repository_slug)
    if git_service == _UPLOAD_PACK:
        permissions.require_permission(identity.permissions, permissions.SOURCE_READ)
        return
    if git_service == _RECEIVE_PACK:
        if not any(p in identity.permissions for p in _RECEIVE_PERMISSIONS):
            raise PermissionDenied("missing permission to push")
        return
    raise PermissionDenied(f"unsupported git service: {git_service}")


class SmartHttpHandler:
    """Validates, authorizes, and proxies one Smart-HTTP request."""

    def __init__(
        self,
        config: ServiceConfig,
        database: Database,
        jwt_service: JwtService,
        repositories: RepositoryStore,
    ):
        self._config = config
        self._db = database
        self._jwt = jwt_service
        self._repos = repositories

    def handle(
        self,
        method: str,
        repository_id: str,
        subpath: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
    ) -> GitHttpResponse:
        token = _extract_token(headers)
        if not token:
            return _auth_challenge("missing credentials")
        try:
            identity, slug = self._authenticate(token, repository_id)
            git_service = _resolve_service(method, subpath, query_string)
            authorize_git_service(identity, slug, git_service)
        except AuthenticationError as exc:
            return _auth_challenge(str(exc))
        except PermissionDenied as exc:
            return GitHttpResponse(403, {"Content-Type": "text/plain"}, str(exc).encode())
        return self._proxy(method, repository_id, subpath, query_string, headers, body, identity)

    def _authenticate(
        self, token: str, repository_id: str
    ) -> tuple[AuthenticatedIdentity, str]:
        with self._db.connect() as conn:
            identity = self._jwt.validate(conn, token)
            repo = self._repos.get(conn, repository_id)
        if repo.organization_id != identity.organization_id:
            raise PermissionDenied("repository belongs to another organization")
        return identity, repo.slug

    def _proxy(
        self,
        method: str,
        repository_id: str,
        subpath: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
        identity: AuthenticatedIdentity,
    ) -> GitHttpResponse:
        env = {
            "GIT_PROJECT_ROOT": str(self._config.repo_storage_root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": f"/{repository_id}.git/{subpath}",
            "REQUEST_METHOD": method,
            "QUERY_STRING": query_string,
            "CONTENT_TYPE": headers.get("content-type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "REMOTE_USER": identity.user_id,
            "BEAGLE_PUSH_USER": identity.user_id,
        }
        protocol = headers.get("git-protocol")
        if protocol:
            env["GIT_PROTOCOL"] = protocol
        result = subprocess.run(
            [self._config.git_binary, "http-backend"],
            input=body,
            capture_output=True,
            env=env,
        )
        if result.returncode != 0:
            raise ServiceError(f"git http-backend failed: {result.stderr.decode().strip()}")
        return _parse_cgi(result.stdout)


def _extract_token(headers: dict[str, str]) -> str | None:
    value = headers.get("authorization")
    if not value:
        return None
    scheme, _, rest = value.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        return rest.strip() or None
    if scheme == "basic":
        try:
            decoded = base64.b64decode(rest).decode()
        except (ValueError, UnicodeDecodeError):
            return None
        username, _, password = decoded.partition(":")
        return password or username or None
    return None


def _resolve_service(method: str, subpath: str, query_string: str) -> str:
    if method == "GET" and subpath == "info/refs":
        for pair in query_string.split("&"):
            key, _, value = pair.partition("=")
            if key == "service":
                return value
        raise PermissionDenied("info/refs requires a service")
    if subpath in (_UPLOAD_PACK, _RECEIVE_PACK):
        return subpath
    raise PermissionDenied(f"unsupported git path: {subpath}")


def _auth_challenge(message: str) -> GitHttpResponse:
    return GitHttpResponse(
        401,
        {"WWW-Authenticate": 'Basic realm="Beagle"', "Content-Type": "text/plain"},
        message.encode(),
    )


def _parse_cgi(output: bytes) -> GitHttpResponse:
    separator = b"\r\n\r\n" if b"\r\n\r\n" in output else b"\n\n"
    raw_headers, _, body = output.partition(separator)
    status = 200
    headers: dict[str, str] = {}
    for line in raw_headers.decode("latin-1").splitlines():
        name, _, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if name.lower() == "status":
            status = int(value.split()[0])
        elif name:
            headers[name] = value
    return GitHttpResponse(status, headers, body)
