from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer
from beagle.service.errors import PermissionDenied
from beagle.service.revision_indexer import search_snapshot_entities


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _upstream(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "--quiet", "-b", "main")
    (path / "shop.py").write_text("def charge():\n    return 1\n")
    _git(path, "add", "shop.py")
    _git(path, "commit", "--quiet", "-m", "base")


@pytest.fixture
def synced(config, tmp_path):
    _upstream(tmp_path / "upstream")
    container = ServiceContainer(config).setup()
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        user = container.identity.create_user(conn, org.id, "dev", "Dev", "dev@e.com")
        other = container.identity.create_user(conn, org.id, "other", "Other", "o@e.com")
        repo = container.repository_service.register(conn, org.id, "shop", "Shop", str(tmp_path / "upstream"))
        container.repository_service.sync(conn, repo.id)
    return container, repo.id, user.id, other.id


# A patch that adds a new function on top of the base commit.
_PATCH = """diff --git a/shop.py b/shop.py
index 0000000..1111111 100644
--- a/shop.py
+++ b/shop.py
@@ -1,2 +1,5 @@
 def charge():
     return 1
+
+def overlay_only():
+    return 2
"""


def test_overlay_snapshot_reflects_patch(synced):
    container, repo_id, user_id, _ = synced
    base = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    overlay = container.workspace_service.create(user_id, repo_id, base, _PATCH)
    assert overlay.snapshot_id is not None
    artifact = str(container.workspace_service.artifact_path(overlay.id))
    # The overlay-only function exists in the workspace snapshot.
    assert search_snapshot_entities(artifact, "overlay_only")
    # And the base snapshot (no patch) does not contain it.
    base_snap = container.revision_indexer.index_revision(repo_id, base)
    assert not search_snapshot_entities(base_snap.artifact_path, "overlay_only")


def test_workspace_ownership_and_sharing(synced):
    container, repo_id, user_id, other_id = synced
    base = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    overlay = container.workspace_service.create(user_id, repo_id, base, _PATCH)
    with container.database.connect() as conn:
        # Owner can read; other user cannot until shared.
        container.workspaces.authorize_read(conn, overlay.id, user_id)
        with pytest.raises(PermissionDenied):
            container.workspaces.authorize_read(conn, overlay.id, other_id)
        container.workspaces.share(conn, overlay.id, other_id)
        container.workspaces.authorize_read(conn, overlay.id, other_id)


def test_workspace_update_reindexes(synced):
    container, repo_id, user_id, _ = synced
    base = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    overlay = container.workspace_service.create(user_id, repo_id, base, "")
    artifact = str(container.workspace_service.artifact_path(overlay.id))
    assert not search_snapshot_entities(artifact, "overlay_only")
    container.workspace_service.update(overlay.id, _PATCH)
    assert search_snapshot_entities(artifact, "overlay_only")


def test_workspace_delete(synced):
    container, repo_id, user_id, _ = synced
    base = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    overlay = container.workspace_service.create(user_id, repo_id, base, _PATCH)
    with container.database.connect() as conn:
        container.workspaces.delete(conn, overlay.id)
        from beagle.service.errors import NotFound
        with pytest.raises(NotFound):
            container.workspaces.get(conn, overlay.id)
