from __future__ import annotations

from pathlib import Path

import pytest

from beagle.context import ContextCompiler
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

PKG = {
    "__init__.py": "",
    "base.py": "class Base:\n    def run(self):\n        return 1\n",
    "worker.py": (
        "from pkg.base import Base\n\n\n"
        "def helper():\n    return 0\n\n\n"
        "class Worker(Base):\n"
        "    def run(self):\n        helper()\n        return self.step()\n\n"
        "    def step(self):\n        return helper()\n"
    ),
    "entry.py": (
        "from pkg.worker import Worker\n\n\n"
        "def main():\n    return Worker().run()\n"
    ),
}


@pytest.fixture
def ws(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for name, body in PKG.items():
        (pkg / name).write_text(body)
    w = Workspace(tmp_path)
    w.index()
    yield w
    w.close()


def test_resolve_by_name(ws):
    matches = GraphService(ws.repo).resolve("Worker")
    assert any(m.id == "python://pkg.worker#Worker" for m in matches)


def test_callees(ws):
    graph = GraphService(ws.repo)
    targets = {e.target_id for e in graph.callees("python://pkg.worker#Worker.run")}
    assert "python://pkg.worker#helper" in targets
    assert "python://pkg.worker#Worker.step" in targets


def test_callers(ws):
    graph = GraphService(ws.repo)
    sources = {e.source_id for e in graph.callers("python://pkg.worker#helper")}
    assert "python://pkg.worker#Worker.run" in sources
    assert "python://pkg.worker#Worker.step" in sources


def test_path(ws):
    graph = GraphService(ws.repo)
    trail = graph.path("python://pkg.entry#main", "python://pkg.worker#helper")
    assert trail is not None
    assert trail[0] == "python://pkg.entry#main"
    assert trail[-1] == "python://pkg.worker#helper"


def test_impact(ws):
    graph = GraphService(ws.repo)
    reachers = {n.entity_id for n in graph.impact("python://pkg.worker#helper")}
    assert "python://pkg.worker#Worker.run" in reachers


def test_context_understand(ws):
    compiler = ContextCompiler(
        ws.repo, GraphService(ws.repo), SearchEngine(ws.db), ws.read_range
    )
    bundle = compiler.compile("understand", "How does Worker run work?", max_tokens=4000)
    ids = {i.entity_id for i in bundle.items}
    assert "python://pkg.worker#Worker" in ids or "python://pkg.worker#Worker.run" in ids
    assert bundle.used_tokens <= bundle.max_tokens


def test_context_budget_enforced(ws):
    compiler = ContextCompiler(
        ws.repo, GraphService(ws.repo), SearchEngine(ws.db), ws.read_range
    )
    bundle = compiler.compile("understand", "Worker helper Base run", max_tokens=20)
    assert bundle.used_tokens <= 20 or len(bundle.items) == 1
