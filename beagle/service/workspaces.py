"""Workspace overlay persistence and access control (design/15 §15).

A workspace overlay is a base commit plus a user's local patch. It belongs to the
authenticated user; another user may read it only through an explicit share.
Patch bytes live on disk under the storage root; this store owns the metadata.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.config import ServiceConfig
from beagle.service.db import Connection
from beagle.service.errors import NotFound, PermissionDenied
from beagle.service.models import WorkspaceOverlay


class WorkspaceStore:
    """CRUD, sharing, and patch storage for workspace overlays."""

    def __init__(self, config: ServiceConfig):
        self._root = config.repo_storage_root / "workspaces"

    def create(
        self, conn: Connection, user_id: str, repository_id: str, base_commit: str,
        patch: str, dirty_tree_hash: str = "", expiry: str | None = None,
    ) -> WorkspaceOverlay:
        workspace_id = ids._new("ws")
        patch_hash = hashlib.sha256(patch.encode()).hexdigest()
        patch_path = self._write_patch(workspace_id, patch)
        now = now_iso()
        overlay = WorkspaceOverlay(
            workspace_id, user_id, repository_id, base_commit, patch_hash,
            dirty_tree_hash, patch_path, None, "private", now, now, expiry,
        )
        conn.execute(
            "INSERT INTO workspace_overlays(id, user_id, repository_id, base_commit,"
            " patch_hash, dirty_tree_hash, patch_path, snapshot_id, sharing_state,"
            " created_at, updated_at, expiry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (workspace_id, user_id, repository_id, base_commit, patch_hash,
             dirty_tree_hash, patch_path, None, "private", now, now, expiry),
        )
        return overlay

    def update_patch(
        self, conn: Connection, workspace_id: str, patch: str, dirty_tree_hash: str = ""
    ) -> WorkspaceOverlay:
        overlay = self.get(conn, workspace_id)
        patch_hash = hashlib.sha256(patch.encode()).hexdigest()
        self._write_patch(workspace_id, patch)
        conn.execute(
            "UPDATE workspace_overlays SET patch_hash = ?, dirty_tree_hash = ?,"
            " snapshot_id = NULL, updated_at = ? WHERE id = ?",
            (patch_hash, dirty_tree_hash, now_iso(), workspace_id),
        )
        return self.get(conn, workspace_id)

    def set_snapshot(self, conn: Connection, workspace_id: str, snapshot_id: str) -> None:
        conn.execute(
            "UPDATE workspace_overlays SET snapshot_id = ? WHERE id = ?",
            (snapshot_id, workspace_id),
        )

    def share(self, conn: Connection, workspace_id: str, user_id: str) -> None:
        self.get(conn, workspace_id)
        if conn.fetch_one(
            "SELECT workspace_id FROM workspace_shares WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        ):
            return
        conn.execute(
            "INSERT INTO workspace_shares(workspace_id, user_id) VALUES (?, ?)",
            (workspace_id, user_id),
        )
        conn.execute(
            "UPDATE workspace_overlays SET sharing_state = 'shared' WHERE id = ?",
            (workspace_id,),
        )

    def delete(self, conn: Connection, workspace_id: str) -> None:
        overlay = self.get(conn, workspace_id)
        conn.execute("DELETE FROM workspace_shares WHERE workspace_id = ?", (workspace_id,))
        conn.execute("DELETE FROM workspace_overlays WHERE id = ?", (workspace_id,))
        Path(overlay.patch_path).unlink(missing_ok=True)

    def get(self, conn: Connection, workspace_id: str) -> WorkspaceOverlay:
        row = conn.fetch_one(
            "SELECT * FROM workspace_overlays WHERE id = ?", (workspace_id,)
        )
        if not row:
            raise NotFound(f"workspace not found: {workspace_id}")
        return WorkspaceOverlay(**row)

    def authorize_read(
        self, conn: Connection, workspace_id: str, user_id: str
    ) -> WorkspaceOverlay:
        """Return the overlay if ``user_id`` owns it or it is shared with them."""
        overlay = self.get(conn, workspace_id)
        if overlay.user_id == user_id:
            return overlay
        shared = conn.fetch_one(
            "SELECT workspace_id FROM workspace_shares WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        )
        if not shared:
            raise PermissionDenied("workspace not shared with this user")
        return overlay

    def read_patch(self, overlay: WorkspaceOverlay) -> str:
        path = Path(overlay.patch_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _write_patch(self, workspace_id: str, patch: str) -> str:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{workspace_id}.patch"
        path.write_text(patch, encoding="utf-8")
        return str(path)
