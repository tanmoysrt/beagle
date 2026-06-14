from __future__ import annotations

import subprocess
from pathlib import Path

import os
import pytest

from beagle.service.errors import Conflict
from beagle.service.git.mirror import GitMirror
from beagle.service.repositories import RepositoryStore
from beagle.service.repository_service import RepositoryService


def _make_upstream(path: Path) -> None:
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    run = lambda *a: subprocess.run(["git", *a], cwd=path, env=env, check=True,
                                    capture_output=True, text=True)
    run("init", "--quiet", "-b", "main")
    (path / "f.txt").write_text("x\n")
    run("add", "f.txt")
    run("commit", "--quiet", "-m", "c1")


@pytest.fixture
def service(config):
    config.repo_storage_root.mkdir(parents=True, exist_ok=True)
    return RepositoryService(RepositoryStore(), GitMirror(config))


def _org(db, identity):
    with db.connect() as conn:
        return identity.create_organization(conn, "frappe", "Frappe").id


def test_register_then_sync(db, identity, service, tmp_path):
    org_id = _org(db, identity)
    _make_upstream(tmp_path / "upstream")
    with db.connect() as conn:
        repo = service.register(
            conn, org_id, "press", "Press", str(tmp_path / "upstream")
        )
        assert repo.storage_path.endswith(f"{repo.id}.git")
    with db.connect() as conn:
        result = service.sync(conn, repo.id)
        assert result.ingestion_state == "synced"
        assert result.ref_count >= 1
    with db.connect() as conn:
        refs = RepositoryStore().list_refs(conn, repo.id)
        assert any(r.namespace == "upstream" for r in refs)


def test_duplicate_slug_rejected(db, identity, service, tmp_path):
    org_id = _org(db, identity)
    with db.connect() as conn:
        service.register(conn, org_id, "press", "Press", None)
    with db.connect() as conn:
        with pytest.raises(Conflict):
            service.register(conn, org_id, "press", "Press 2", None)
