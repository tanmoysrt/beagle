from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer
from beagle.service.revision_indexer import search_snapshot_entities


def _git(cwd, *args, when=None):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.com",
        "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.com",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True)


def _upstream(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "--quiet", "-b", "main")
    (path / "shop.py").write_text(
        "class Order:\n    def place(self):\n        return charge()\n\n"
        "def charge():\n    return True\n"
    )
    _git(path, "add", "shop.py")
    _git(path, "commit", "--quiet", "-m", "first", when=1_781_400_001)
    # second commit adds a new function
    (path / "shop.py").write_text(
        "class Order:\n    def place(self):\n        return charge()\n\n"
        "def charge():\n    return True\n\ndef refund():\n    return True\n"
    )
    _git(path, "add", "shop.py")
    _git(path, "commit", "--quiet", "-m", "second", when=1_781_400_002)
    # feature branch + merge
    _git(path, "checkout", "--quiet", "-b", "feature")
    (path / "extra.py").write_text("def helper():\n    return 1\n")
    _git(path, "add", "extra.py")
    _git(path, "commit", "--quiet", "-m", "feature work", when=1_781_400_003)
    _git(path, "checkout", "--quiet", "main")
    _git(path, "merge", "--quiet", "--no-ff", "feature", "-m", "merge", when=1_781_400_004)


@pytest.fixture
def synced(config, tmp_path):
    _upstream(tmp_path / "upstream")
    container = ServiceContainer(config).setup()
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        repo = container.repository_service.register(
            conn, org.id, "shop", "Shop", str(tmp_path / "upstream")
        )
        container.repository_service.sync(conn, repo.id)
    return container, repo.id


def _main_sha(container, repo_id):
    return container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")


def test_index_revision_creates_ready_snapshot(synced):
    container, repo_id = synced
    sha = _main_sha(container, repo_id)
    snapshot = container.revision_indexer.index_revision(repo_id, sha)
    assert snapshot.status == "ready"
    assert snapshot.commit_sha == sha
    assert snapshot.entity_count and snapshot.entity_count > 0
    assert Path(snapshot.artifact_path).exists()


def test_snapshot_is_reused(synced):
    container, repo_id = synced
    sha = _main_sha(container, repo_id)
    first = container.revision_indexer.index_revision(repo_id, sha)
    second = container.revision_indexer.index_revision(repo_id, sha)
    assert first.id == second.id  # same manifest, not re-indexed


def test_history_indexed_parent_first_with_reuse(synced):
    container, repo_id = synced
    snapshots = container.revision_indexer.index_history(
        repo_id, "refs/beagle/upstream/heads/main", limit=50
    )
    # first, second, feature work, merge = 4 commits
    assert len(snapshots) == 4
    assert all(s.status == "ready" for s in snapshots)
    with container.database.connect() as conn:
        assert len(container.snapshots.list_for_repository(conn, repo_id)) == 4


def test_revision_search_is_scoped_to_snapshot(synced):
    container, repo_id = synced
    main = _main_sha(container, repo_id)
    first_parent = container.mirror.rev_list(repo_id, main, 50)[0]
    container.revision_indexer.index_revision(repo_id, main)
    container.revision_indexer.index_revision(repo_id, first_parent)

    with container.database.connect() as conn:
        main_snap = container.snapshots.get(conn, repo_id, main)
        first_snap = container.snapshots.get(conn, repo_id, first_parent)
    # refund() exists in later revisions but not in the very first commit.
    assert search_snapshot_entities(main_snap.artifact_path, "refund")
    assert not search_snapshot_entities(first_snap.artifact_path, "refund")


def test_merge_snapshot_has_both_files(synced):
    container, repo_id = synced
    main = _main_sha(container, repo_id)  # merge commit
    snapshot = container.revision_indexer.index_revision(repo_id, main)
    # The merge tree contains both shop.py (refund) and extra.py (helper).
    assert search_snapshot_entities(snapshot.artifact_path, "refund")
    assert search_snapshot_entities(snapshot.artifact_path, "helper")


def test_unknown_revision_raises(synced):
    from beagle.service.errors import NotFound

    container, repo_id = synced
    with pytest.raises(NotFound):
        container.revision_indexer.index_revision(repo_id, "deadbeef")
