"""Ref namespaces and push authorization (design/15 §6).

Canonical upstream refs are updated only by trusted fetch jobs. A user may push
only into their own namespaces. These are pure helpers shared by the mirror,
the Smart-HTTP handler, and the per-repository ``pre-receive`` hook.
"""

from __future__ import annotations

UPSTREAM_HEADS = "refs/beagle/upstream/heads/"
UPSTREAM_TAGS = "refs/beagle/upstream/tags/"
USERS_PREFIX = "refs/beagle/users/"
WORKSPACES_PREFIX = "refs/beagle/workspaces/"

# Refspecs used when fetching upstream into the canonical namespace. Forced so a
# rewritten upstream branch updates the mirror pointer (force-push handling).
UPSTREAM_FETCH_REFSPECS = [
    "+refs/heads/*:refs/beagle/upstream/heads/*",
    "+refs/tags/*:refs/beagle/upstream/tags/*",
]


def upstream_head(branch: str) -> str:
    return f"{UPSTREAM_HEADS}{branch}"


def upstream_tag(tag: str) -> str:
    return f"{UPSTREAM_TAGS}{tag}"


def user_head(user_id: str, branch: str) -> str:
    return f"{USERS_PREFIX}{user_id}/heads/{branch}"


def workspace_ref(user_id: str, workspace_id: str) -> str:
    return f"{WORKSPACES_PREFIX}{user_id}/{workspace_id}"


def classify_namespace(ref: str) -> str:
    if ref.startswith(UPSTREAM_HEADS) or ref.startswith(UPSTREAM_TAGS):
        return "upstream"
    if ref.startswith(USERS_PREFIX):
        return "user"
    if ref.startswith(WORKSPACES_PREFIX):
        return "workspace"
    return "other"


def is_push_allowed(user_id: str, ref: str) -> bool:
    """True only when ``user_id`` owns the namespace ``ref`` lives in.

    Pushes to upstream, to another user's namespace, or outside the Beagle
    namespaces are always rejected. An empty user id authorizes nothing.
    """
    if not user_id:
        return False
    return ref.startswith(f"{USERS_PREFIX}{user_id}/") or ref.startswith(
        f"{WORKSPACES_PREFIX}{user_id}/"
    )
