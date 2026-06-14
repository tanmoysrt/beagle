from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from beagle.service.git.mirror import GitMirror
from beagle.service.errors import NotFound


def _make_upstream(path: Path) -> str:
    """Create a real upstream repo with one commit and a tag; return HEAD sha."""
    path.mkdir(parents=True)
    env = {
        "GIT_AUTHOR_NAME": "Up Stream",
        "GIT_AUTHOR_EMAIL": "up@example.com",
        "GIT_COMMITTER_NAME": "Up Stream",
        "GIT_COMMITTER_EMAIL": "up@example.com",
    }

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=path, env={**__import__("os").environ, **env},
            capture_output=True, text=True, check=True,
        )

    git("init", "--quiet", "-b", "main")
    (path / "README.md").write_text("hello\n")
    git("add", "README.md")
    git("commit", "--quiet", "-m", "initial commit")
    git("tag", "v1.0")
    return git("rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def mirror(config):
    config.repo_storage_root.mkdir(parents=True, exist_ok=True)
    return GitMirror(config)


def test_init_bare_installs_hook(mirror):
    path = mirror.init_bare("repo_abc")
    assert path.exists()
    hook = path / "hooks" / "pre-receive"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111  # executable


def test_fetch_upstream_into_namespace(mirror, tmp_path):
    head = _make_upstream(tmp_path / "upstream")
    mirror.init_bare("repo_abc")
    mirror.set_upstream("repo_abc", str(tmp_path / "upstream"))
    entries = mirror.fetch_upstream("repo_abc")
    names = {e.ref_name for e in entries}
    assert "refs/beagle/upstream/heads/main" in names
    assert "refs/beagle/upstream/tags/v1.0" in names
    # Only the canonical namespace is populated — no refs/remotes/* pollution.
    assert all(n.startswith("refs/beagle/upstream/") for n in names)
    assert mirror.has_commit("repo_abc", head)
    assert mirror.resolve("repo_abc", "refs/beagle/upstream/heads/main") == head


def test_integrity_check_passes_on_clean_repo(mirror, tmp_path):
    _make_upstream(tmp_path / "upstream")
    mirror.init_bare("repo_abc")
    mirror.set_upstream("repo_abc", str(tmp_path / "upstream"))
    mirror.fetch_upstream("repo_abc")
    mirror.verify_integrity("repo_abc")  # must not raise


def test_operations_on_unknown_repo_raise(mirror):
    with pytest.raises(NotFound):
        mirror.list_refs("repo_missing")


def test_unknown_revision_resolves_to_none(mirror):
    mirror.init_bare("repo_abc")
    assert mirror.resolve("repo_abc", "deadbeef") is None
    assert not mirror.has_commit("repo_abc", "deadbeef")
