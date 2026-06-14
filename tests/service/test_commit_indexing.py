from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer
from beagle.service.git.commit_reader import _parse_trailers, _parse_shortstat


_BASE_TIME = 1_781_400_000


def _run(cwd, *args, author=("Auth", "auth@e.com"), committer=("Comm", "comm@e.com"),
         when=None):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1],
    }
    if when is not None:
        stamp = f"{when} +0000"
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True)


def _rich_upstream(path: Path) -> None:
    path.mkdir(parents=True)
    _run(path, "init", "--quiet", "-b", "main")
    (path / "a.txt").write_text("a\n")
    _run(path, "add", "a.txt")
    _run(path, "commit", "--quiet", "-m", "first: add a", when=_BASE_TIME + 1)
    # Commit with trailers and a distinct author vs committer.
    (path / "b.txt").write_text("b\n")
    _run(path, "add", "b.txt")
    _run(path, "commit", "--quiet", "-m",
         "feat: add b\n\nBody text.\n\nCo-authored-by: Alice <alice@example.com>\n"
         "Signed-off-by: Bob <bob@example.com>",
         author=("Tanmoy", "tanmoy@example.com"), committer=("Maint", "maint@example.com"),
         when=_BASE_TIME + 2)
    # Feature branch + non-fast-forward merge.
    _run(path, "checkout", "--quiet", "-b", "feature")
    (path / "c.txt").write_text("c\n")
    _run(path, "add", "c.txt")
    _run(path, "commit", "--quiet", "-m", "feat: add c on feature", when=_BASE_TIME + 3)
    _run(path, "checkout", "--quiet", "main")
    _run(path, "merge", "--quiet", "--no-ff", "feature", "-m", "Merge feature into main",
         when=_BASE_TIME + 4)


@pytest.fixture
def synced(config, tmp_path):
    _rich_upstream(tmp_path / "upstream")
    container = ServiceContainer(config).setup()
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        repo = container.repository_service.register(
            conn, org.id, "press", "Press", str(tmp_path / "upstream")
        )
        result = container.repository_service.sync(conn, repo.id)
    return container, repo.id, result


def test_all_commits_indexed(synced):
    container, repo_id, result = synced
    # four commits: first, feat-b, feat-c, merge
    assert result.commit_count == 4
    with container.database.connect() as conn:
        assert container.commits.count(conn, repo_id) == 4


def test_incremental_sync_adds_nothing(synced):
    container, repo_id, _ = synced
    with container.database.connect() as conn:
        second = container.repository_service.sync(conn, repo_id)
    assert second.commit_count == 0


def test_history_newest_first(synced):
    container, repo_id, _ = synced
    with container.database.connect() as conn:
        history = container.commits.history(conn, repo_id)
    assert history[0]["subject"] == "Merge feature into main"
    assert history[0]["is_merge"] == 1


def test_author_and_committer_kept_separate(synced):
    container, repo_id, _ = synced
    with container.database.connect() as conn:
        matches = container.commits.search(conn, repo_id, "add b")
    commit = matches[0]
    assert commit["author_name"] == "Tanmoy"
    assert commit["author_email"] == "tanmoy@example.com"
    assert commit["committer_name"] == "Maint"
    assert commit["committer_email"] == "maint@example.com"


def test_trailers_parsed_and_searchable(synced):
    container, repo_id, _ = synced
    with container.database.connect() as conn:
        matches = container.commits.search(conn, repo_id, "add b")
        detail = container.commits.get_commit(conn, repo_id, matches[0]["sha"])
        # Searchable by trailer value (a co-author email).
        by_trailer = container.commits.search(conn, repo_id, "alice@example.com")
    keys = {t["key"] for t in detail["trailers"]}
    assert keys == {"Co-authored-by", "Signed-off-by"}
    assert by_trailer and by_trailer[0]["sha"] == matches[0]["sha"]


def test_merge_commit_has_two_parents(synced):
    container, repo_id, _ = synced
    with container.database.connect() as conn:
        merge = container.commits.search(conn, repo_id, "Merge feature")[0]
        detail = container.commits.get_commit(conn, repo_id, merge["sha"])
    assert len(detail["parents"]) == 2


def test_trailer_parser_unit():
    body = "Fix bug.\n\nReviewed-by: A <a@x>\nFixes: #12"
    assert _parse_trailers(body) == [("Reviewed-by", "A <a@x>"), ("Fixes", "#12")]
    # No trailing trailer block.
    assert _parse_trailers("just a message") == []


def test_shortstat_parser_unit():
    assert _parse_shortstat(" 2 files changed, 10 insertions(+), 3 deletions(-)") == (2, 10, 3)
    assert _parse_shortstat(" 1 file changed, 5 insertions(+)") == (1, 5, 0)
    assert _parse_shortstat("") == (None, None, None)
