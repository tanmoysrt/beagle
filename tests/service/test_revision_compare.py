from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer


def _git(cwd, *args, when=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@e.com",
           "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@e.com"}
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True)


def _upstream(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "--quiet", "-b", "main")
    (path / "shop.py").write_text("def charge():\n    return 1\n")
    _git(path, "add", "shop.py")
    _git(path, "commit", "--quiet", "-m", "base", when=1_781_400_001)
    # change charge signature + add refund + add a new file
    (path / "shop.py").write_text("def charge(amount):\n    return amount\n\ndef refund():\n    return 1\n")
    (path / "new.py").write_text("def added():\n    return 1\n")
    _git(path, "add", "shop.py", "new.py")
    _git(path, "commit", "--quiet", "-m", "head changes", when=1_781_400_002)


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


def _shas(container, repo_id):
    head = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    base = container.mirror.rev_list(repo_id, head, 50)[0]
    return base, head


def test_compare_reports_files_entities_commits(synced):
    container, repo_id = synced
    base, head = _shas(container, repo_id)
    result = container.revision_comparer.compare(repo_id, base, head)
    paths = {c["path"] for c in result.changed_files}
    assert paths == {"shop.py", "new.py"}

    added = {e["name"] for e in result.entities_added}
    changed = {e["name"] for e in result.entities_changed}
    assert "refund" in added and "added" in added
    assert "charge" in changed  # signature changed (gained a parameter)

    assert len(result.commits) == 1
    assert result.commits[0]["subject"] == "head changes"
    assert result.authors == ["dev@e.com"]


def test_compare_is_directional(synced):
    container, repo_id = synced
    base, head = _shas(container, repo_id)
    reverse = container.revision_comparer.compare(repo_id, head, base)
    removed = {e["name"] for e in reverse.entities_removed}
    assert "refund" in removed and "added" in removed


def test_branch_compare_uses_merge_base(synced):
    container, repo_id = synced
    base, head = _shas(container, repo_id)
    comparison = container.revision_comparer.branch_compare(repo_id, base, head)
    assert comparison.merge_base == base
    # target == base vs base -> no changes; source == head vs base -> changes
    assert comparison.target.changed_files == []
    assert comparison.source.changed_files
