"""Permission vocabulary and checks (design/15 §3).

Permissions are flat string scopes carried in the JWT. Repository scoping is a
separate axis: a token lists the repositories it may touch by slug. A request is
authorized only when the token holds the required permission *and* (for
repository-bound operations) names the target repository.
"""

from __future__ import annotations

from beagle.service.errors import PermissionDenied

SOURCE_READ = "source:read"
REPO_REGISTER = "repo:register"
REPO_SYNC = "repo:sync"
WORKSPACE_CREATE = "workspace:create"
WORKSPACE_SHARE = "workspace:share"
DECISION_READ = "decision:read"
DECISION_WRITE = "decision:write"
FEEDBACK_READ = "feedback:read"
FEEDBACK_WRITE = "feedback:write"
ADMIN_IDENTITY = "admin:identity"

ALL_PERMISSIONS = frozenset(
    {
        SOURCE_READ,
        REPO_REGISTER,
        REPO_SYNC,
        WORKSPACE_CREATE,
        WORKSPACE_SHARE,
        DECISION_READ,
        DECISION_WRITE,
        FEEDBACK_READ,
        FEEDBACK_WRITE,
        ADMIN_IDENTITY,
    }
)

# Writes that must never succeed unauthenticated/unauthorized (design §24 Phase A).
WRITE_PERMISSIONS = frozenset(
    {
        REPO_REGISTER,
        REPO_SYNC,
        WORKSPACE_CREATE,
        WORKSPACE_SHARE,
        DECISION_WRITE,
        FEEDBACK_WRITE,
        ADMIN_IDENTITY,
    }
)


def validate_permissions(permissions: list[str]) -> list[str]:
    """Reject unknown permission strings at mint time; preserve order."""
    unknown = [p for p in permissions if p not in ALL_PERMISSIONS]
    if unknown:
        raise PermissionDenied(f"unknown permissions: {', '.join(sorted(unknown))}")
    return list(dict.fromkeys(permissions))


def require_permission(granted: list[str], needed: str) -> None:
    if needed not in granted:
        raise PermissionDenied(f"missing permission: {needed}")


def require_repository(allowed: list[str], repository_slug: str) -> None:
    if repository_slug not in allowed:
        raise PermissionDenied(f"token not scoped to repository: {repository_slug}")
