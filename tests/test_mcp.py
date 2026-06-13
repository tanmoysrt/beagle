from __future__ import annotations

from pathlib import Path

import pytest

from beagle.mcp import BeagleTools
from beagle.workspace import Workspace

PKG = {
    "__init__.py": "",
    "base.py": "class Base:\n    def run(self):\n        return 1\n",
    "worker.py": (
        "from pkg.base import Base\n\n\n"
        "def helper():\n    return 0\n\n\n"
        "class Worker(Base):\n"
        "    def run(self):\n        return helper()\n"
    ),
}


@pytest.fixture
def tools(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for name, body in PKG.items():
        (pkg / name).write_text(body)
    ws = Workspace(tmp_path)
    ws.index()
    yield BeagleTools(ws)
    ws.close()


def test_index_status(tools):
    status = tools.index_status()
    assert status["counts"]["files"] == 3
    assert status["last_run"]["status"] == "complete"


def test_search(tools):
    hits = tools.search("helper")
    assert any(h["file"] == "pkg/worker.py" for h in hits)


def test_resolve_and_show(tools):
    matches = tools.resolve("Worker")
    assert any(m["entity_id"] == "python://pkg.worker#Worker" for m in matches)
    detail = tools.show("python://pkg.worker#Worker")
    assert detail["kind"] == "class"
    assert "signature" in detail


def test_callees(tools):
    result = tools.callees("python://pkg.worker#Worker.run")
    assert any(e["entity_id"] == "python://pkg.worker#helper" for e in result["callees"])


def test_find_path(tools):
    result = tools.find_path("python://pkg.worker#Worker.run", "python://pkg.worker#helper")
    ids = [p["entity_id"] for p in result["path"]]
    assert ids and ids[-1] == "python://pkg.worker#helper"


def test_ambiguous_returns_candidates(tools):
    result = tools.show("run")
    assert "candidates" in result


def test_read_source(tools):
    result = tools.read_source("python://pkg.worker#helper")
    assert "def helper" in result["source"]


def test_context(tools):
    bundle = tools.context("How does Worker run", intent="understand", max_tokens=2000)
    assert bundle["items"]
    assert bundle["used_tokens"] <= bundle["max_tokens"]


def test_investigate(tools):
    # MCP defaults to the compact structured result (design/11 §17).
    report = tools.investigate("Worker run calls helper")
    assert "primary_workflows" in report
    assert "sources" in report and report["sources"]
    assert "mermaid" not in report  # only when requested


def test_investigate_with_source_and_mermaid(tools):
    report = tools.investigate("Worker run calls helper",
                               include_source=True, include_mermaid=True)
    assert "flowchart TD" in report["mermaid"]
    assert report["source"]  # entity_id -> source text


def test_explain_function(tools):
    result = tools.explain_function("python://pkg.worker#Worker.run", include_mermaid=True)
    assert result["entity_id"] == "python://pkg.worker#Worker.run"
    assert "flowchart TD" in result["mermaid"]


def test_function_context(tools):
    card = tools.function_context("python://pkg.worker#Worker.run", include_mermaid=True)
    assert card["identity"]["entity_id"] == "python://pkg.worker#Worker.run"
    assert "responsibility" in card and "unknowns" in card
    # Worker.run calls helper() -> an important business call
    assert any(c["name"].endswith("helper()") or "helper" in c["name"] for c in card["calls"])
    assert "flowchart TD" in card["mermaid"]


def test_function_context_ambiguous(tools):
    card = tools.function_context("nope_zzz")
    assert "error" in card


def test_change_facts_non_git(tools):
    # The fixture workspace is not a git repo: the tool answers gracefully.
    result = tools.change_facts()
    assert "not a git repository" in result["notes"]


def test_entity_history_empty(tools):
    result = tools.entity_history("python://pkg.worker#helper")
    assert result["entity_id"] == "python://pkg.worker#helper"
    assert result["episodes"] == [] and result["changes"] == []


def test_episode_missing(tools):
    assert "error" in tools.episode("nope")


def test_trace_tool(tools):
    # pure-python fixture: no document operations, but the tool must still answer
    result = tools.trace("python://pkg.worker#Worker.run", depth=1)
    assert "nodes" in result and "edges" in result
