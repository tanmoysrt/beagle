from __future__ import annotations

from pathlib import Path

from beagle.discovery import Scanner, find_repo_root
from beagle.search import SearchEngine
from beagle.workspace import Workspace


def test_scanner_honours_gitignore(repo: Path) -> None:
    found = {d.relpath for d in Scanner(repo).scan()}
    assert "pkg/site.py" in found
    assert "ignored/skip.py" not in found


def test_find_repo_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == tmp_path.resolve()


def test_index_populates_files_and_chunks(workspace: Workspace) -> None:
    summary = workspace.index()
    assert summary["indexed"] == 1
    counts = workspace.repo.counts()
    assert counts["files"] == 1
    assert counts["text_chunks"] >= 1


def test_search_finds_content(workspace: Workspace) -> None:
    workspace.index()
    results = SearchEngine(workspace.db).search("run_deployment")
    assert results
    assert results[0].owner_file == "pkg/site.py"


def test_incremental_change_has_no_stale_facts(workspace: Workspace) -> None:
    workspace.index()
    site = workspace.root / "pkg" / "site.py"
    site.write_text("def renamed_only():\n    return 0\n")
    workspace.index()

    # old token gone, new token present -> no stale chunk survived the change
    engine = SearchEngine(workspace.db)
    assert not engine.search("run_deployment")
    assert engine.search("renamed_only")
    assert workspace.repo.counts()["files"] == 1


def test_deleted_file_removed(workspace: Workspace) -> None:
    workspace.index()
    (workspace.root / "pkg" / "site.py").unlink()
    summary = workspace.index()
    assert summary["deleted"] == 1
    assert workspace.repo.counts()["files"] == 0


def test_unchanged_files_skipped(workspace: Workspace) -> None:
    workspace.index()
    summary = workspace.index()
    assert summary["indexed"] == 0
    assert summary["unchanged"] == 1


def test_read_range(workspace: Workspace) -> None:
    workspace.index()
    text = workspace.read_range("pkg/site.py", 1, 1)
    assert text == "class Site:"
