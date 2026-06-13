from __future__ import annotations

from pathlib import Path

import pytest

from beagle.workspace import Workspace

BASE = '''\
class Base:
    def run(self):
        return 1

    def shared(self):
        return 2
'''

WORKER = '''\
from pkg.base import Base


def helper():
    return 0


class Worker(Base):
    def run(self):
        helper()
        self.shared()
        super().run()
        return 0

    def make(self):
        w = Worker()
        return w.run()
'''

API = '''\
import pkg.worker


def go():
    return pkg.worker.helper()
'''


@pytest.fixture
def graph(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text(BASE)
    (pkg / "worker.py").write_text(WORKER)
    (pkg / "api.py").write_text(API)
    ws = Workspace(tmp_path)
    ws.index()
    yield ws
    ws.close()


def edges(ws: Workspace, relationship: str):
    rows = ws.db.conn.execute(
        "SELECT source_id, target_id, resolver, confidence FROM edges "
        "WHERE relationship = ?",
        (relationship,),
    ).fetchall()
    return [(r["source_id"], r["target_id"], r["resolver"], r["confidence"]) for r in rows]


def has(ws, rel, source_suffix, target):
    return any(
        s.endswith(source_suffix) and t == target for s, t, _, _ in edges(ws, rel)
    )


def test_inherits(graph):
    assert has(graph, "INHERITS", "#Worker", "python://pkg.base#Base")


def test_overrides(graph):
    assert has(graph, "OVERRIDES", "#Worker.run", "python://pkg.base#Base.run")


def test_from_import_resolves_to_entity(graph):
    assert has(graph, "IMPORTS", "pkg.worker", "python://pkg.base#Base")


def test_plain_import_resolves_to_module(graph):
    assert has(graph, "IMPORTS", "pkg.api", "python://pkg.worker")


def test_module_scope_call(graph):
    # Worker.run -> helper() defined in same module
    assert has(graph, "CALLS", "#Worker.run", "python://pkg.worker#helper")


def test_self_inherited_method_call(graph):
    # self.shared() resolves to inherited Base.shared
    rows = edges(graph, "CALLS")
    assert any(
        s.endswith("#Worker.run") and t == "python://pkg.base#Base.shared"
        and resolver == "inherited-method"
        for s, t, resolver, _ in rows
    )


def test_super_call(graph):
    rows = edges(graph, "CALLS")
    assert any(
        s.endswith("#Worker.run") and t == "python://pkg.base#Base.run"
        and resolver == "super"
        for s, t, resolver, _ in rows
    )


def test_type_propagation_call(graph):
    # w = Worker(); w.run() -> Worker.run
    rows = edges(graph, "CALLS")
    assert any(
        s.endswith("#Worker.make") and t == "python://pkg.worker#Worker.run"
        and resolver == "type-propagation"
        for s, t, resolver, _ in rows
    )


def test_dotted_import_call(graph):
    assert has(graph, "CALLS", "#go", "python://pkg.worker#helper")


def test_unresolved_preserved(graph):
    # an unknown call is kept, not dropped
    (Path(graph.root) / "pkg" / "mystery.py").write_text(
        "def f():\n    totally_unknown_function()\n"
    )
    graph.index()
    rows = edges(graph, "CALLS")
    assert any(
        s.endswith("#f") and t is None and resolver == "unresolved"
        for s, t, resolver, _ in rows
    )
