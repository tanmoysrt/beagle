from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from beagle.temporal import TemporalRepository, TemporalService
from beagle.temporal.changes import parse_diff
from beagle.temporal.redact import redact
from beagle.workspace import Workspace

_ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00", "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00",
}

ADD_V1 = "def add(a, b):\n    return a + b\n"
ADD_V2 = "def add(a, b):\n    total = a + b\n    return total\n"


def git(root: Path, *args: str) -> str:
    import os

    env = {**os.environ, **_ENV}
    return subprocess.run(["git", *args], cwd=str(root), env=env,
                          capture_output=True, text=True, check=True).stdout


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path):
    git(tmp_path, "init", "-q")
    write(tmp_path, ".gitignore", ".beagle/\n")
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/calc.py", ADD_V1)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    yield tmp_path


def service_for(root: Path) -> tuple[TemporalService, Workspace]:
    ws = Workspace(root)
    ws.index()
    return TemporalService(root, ws.repo, TemporalRepository(ws.db)), ws


def test_parse_diff_added_and_modified():
    diff = (
        "diff --git a/x.py b/x.py\nnew file mode 100644\n--- /dev/null\n"
        "+++ b/x.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    )
    deltas = parse_diff(diff)
    assert deltas[0].status == "added"
    assert deltas[0].path_after == "x.py"


def test_working_tree_change_maps_to_entity(repo: Path):
    write(repo, "pkg/calc.py", ADD_V2)
    service, ws = service_for(repo)
    report = service.analyze()
    ids = [c.entity_after for c in report.entity_changes]
    assert "python://pkg.calc#add" in ids
    ws.close()


def test_clean_working_tree(repo: Path):
    service, ws = service_for(repo)
    report = service.analyze()
    assert "working tree clean" in report.notes
    ws.close()


def test_single_commit_records_facts(repo: Path):
    write(repo, "pkg/calc.py", ADD_V2)
    git(repo, "commit", "-aqm", "expand add")
    head = git(repo, "rev-parse", "HEAD").strip()
    service, ws = service_for(repo)
    report = service.analyze(head)
    assert report.commits and report.commits[0].message == "expand add"
    assert any(c.entity_after == "python://pkg.calc#add" for c in report.entity_changes)
    assert report.changeset.patch_id
    ws.close()


def test_record_and_entity_history(repo: Path):
    write(repo, "pkg/calc.py", ADD_V2)
    git(repo, "commit", "-aqm", "expand add")
    head = git(repo, "rev-parse", "HEAD").strip()
    service, ws = service_for(repo)
    ep = service.new_episode("Expand add", problem="needed a local")
    service.add_decision(ep.id, "use an intermediate variable")
    service.record(service.analyze(head), episode_id=ep.id)
    hist = service.entity_history("python://pkg.calc#add")
    assert ep.id in [e.id for e in hist["episodes"]]
    assert any("intermediate" in d.statement for d in hist["decisions"])
    ws.close()


def test_supersede_keeps_old_decision_labelled(repo: Path):
    service, ws = service_for(repo)
    ep = service.new_episode("Retry policy")
    d1 = service.add_decision(ep.id, "retry forever")
    service.supersede_decision(d1.id, ep.id, "retry with cooldown")
    bundle = service.episode_bundle(ep.id)
    statuses = {d.id: d.status for d in bundle["decisions"]}
    assert statuses[d1.id] == "superseded"
    assert len(bundle["decisions"]) == 2  # old one kept, not deleted
    ws.close()


def test_rejected_alternative_preserved(repo: Path):
    service, ws = service_for(repo)
    ep = service.new_episode("TLS retry")
    service.add_alternative(ep.id, "remove the max attempt limit", "could retry forever")
    alts = service.episode_bundle(ep.id)["alternatives"]
    assert alts and alts[0].status == "rejected"
    ws.close()


def test_secret_is_redacted(repo: Path):
    service, ws = service_for(repo)
    ep = service.new_episode("Add token")
    d = service.add_decision(ep.id, "set api_key=SECRETVALUE12345 in config")
    assert "SECRETVALUE12345" not in d.statement
    assert "[REDACTED]" in d.statement
    ws.close()


def test_rename_detected(repo: Path):
    git(repo, "mv", "pkg/calc.py", "pkg/math_calc.py")
    git(repo, "commit", "-qm", "rename calc")
    head = git(repo, "rev-parse", "HEAD").strip()
    service, ws = service_for(repo)
    report = service.analyze(head)
    assert any(c.change_type == "renamed" for c in report.entity_changes)
    ws.close()


def test_patch_id_matches_changeset(repo: Path):
    write(repo, "pkg/calc.py", ADD_V2)
    git(repo, "commit", "-aqm", "expand add")
    head = git(repo, "rev-parse", "HEAD").strip()
    service, ws = service_for(repo)
    ep = service.new_episode("Expand add")
    service.record(service.analyze(head), episode_id=ep.id)
    match = service.match_changeset(service.analyze(head))
    assert match is not None and match.episode_id == ep.id
    ws.close()


def test_git_note_round_trip(repo: Path):
    write(repo, "pkg/calc.py", ADD_V2)
    git(repo, "commit", "-aqm", "expand add")
    head = git(repo, "rev-parse", "HEAD").strip()
    service, ws = service_for(repo)
    ep = service.new_episode("Expand add")
    service.attach_commit(head, ep.id, write_note=True)
    assert service.notes.read(head)["episode_id"] == ep.id
    ws.close()


def test_redact_helper():
    assert redact("token=abc123def") == "[REDACTED]"
    assert redact("plain text") == "plain text"
