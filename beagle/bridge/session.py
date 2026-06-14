"""Bridge synchronization handshake (design/15 §7, Phase F).

Decides what must be synchronized for the current local HEAD and does the
minimum: push only missing commits to the user's own ref namespace, then index
if no snapshot exists. Already-synced commits upload nothing. Local-only mode
uploads nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from beagle.bridge.client import ServiceClient
from beagle.bridge.local_repo import LocalRepository
from beagle.service.git import refs


@dataclass
class SyncOutcome:
    head: str
    branch: str
    pushed: bool
    indexed: bool
    dirty: bool
    local_only: bool
    workspace_id: str | None = None


class BridgeSession:
    """Connects a local repository to the shared service."""

    def __init__(self, client: ServiceClient, local: LocalRepository):
        self._client = client
        self._local = local

    def connect(self) -> dict:
        """Authenticate and return the service's view of the current user."""
        return self._client.whoami()

    def ensure_head_synced(
        self, repository_slug: str, local_only: bool = False, upload_dirty: bool = False
    ) -> SyncOutcome:
        identity = self._client.whoami()
        head = self._local.head_sha()
        branch = self._local.branch()
        dirty = self._local.is_dirty()
        if local_only:
            return SyncOutcome(head, branch, False, False, dirty, True)

        repo = self._client.find_repository(repository_slug)
        status = self._client.sync_status(repo["id"], head)
        pushed = self._push_if_missing(identity, repo["id"], head, branch, status)
        indexed = self._index_if_missing(repo["id"], head, status)
        workspace_id = self._upload_overlay(repo["id"], head) if (dirty and upload_dirty) else None
        return SyncOutcome(head, branch, pushed, indexed, dirty, False, workspace_id)

    def _upload_overlay(self, repository_id: str, head: str) -> str:
        """Send uncommitted changes as a workspace overlay (design §15)."""
        overlay = self._client.create_workspace(
            repository_id, head, self._local.dirty_patch(), self._local.dirty_fingerprint()
        )
        return overlay["id"]

    def _push_if_missing(
        self, identity: dict, repository_id: str, head: str, branch: str, status: dict
    ) -> bool:
        if status["has_commit"]:
            return False  # avoid repeated uploads
        ref = refs.user_head(identity["user"]["id"], branch)
        self._client.push_ref(self._local, repository_id, f"HEAD:{ref}")
        return True

    def _index_if_missing(self, repository_id: str, head: str, status: dict) -> bool:
        if status["has_snapshot"]:
            return False
        self._client.index_revision(repository_id, head)
        return True
