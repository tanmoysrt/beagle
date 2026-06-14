from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.git.mirror import GitMirror


def _git(cwd, *args, env_extra=None, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          check=check)


@pytest.fixture
def work_repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--quiet", "-b", "main")
    (work / "a.txt").write_text("a\n")
    _git(work, "add", "a.txt")
    _git(work, "commit", "--quiet", "-m", "c1")
    return work


def test_push_to_own_namespace_allowed(config, work_repo):
    config.repo_storage_root.mkdir(parents=True, exist_ok=True)
    bare = GitMirror(config).init_bare("repo_1")
    _git(work_repo, "remote", "add", "beagle", str(bare))
    result = _git(
        work_repo, "push", "beagle", "HEAD:refs/beagle/users/user_42/heads/wip",
        env_extra={"BEAGLE_PUSH_USER": "user_42"}, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_push_to_upstream_denied(config, work_repo):
    config.repo_storage_root.mkdir(parents=True, exist_ok=True)
    bare = GitMirror(config).init_bare("repo_1")
    _git(work_repo, "remote", "add", "beagle", str(bare))
    result = _git(
        work_repo, "push", "beagle", "HEAD:refs/beagle/upstream/heads/main",
        env_extra={"BEAGLE_PUSH_USER": "user_42"}, check=False,
    )
    assert result.returncode != 0
    assert "denied" in result.stderr


def test_push_to_other_users_namespace_denied(config, work_repo):
    config.repo_storage_root.mkdir(parents=True, exist_ok=True)
    bare = GitMirror(config).init_bare("repo_1")
    _git(work_repo, "remote", "add", "beagle", str(bare))
    result = _git(
        work_repo, "push", "beagle", "HEAD:refs/beagle/users/user_99/heads/wip",
        env_extra={"BEAGLE_PUSH_USER": "user_42"}, check=False,
    )
    assert result.returncode != 0
    assert "denied" in result.stderr
