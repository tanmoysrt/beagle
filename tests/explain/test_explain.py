from __future__ import annotations

from pathlib import Path

import pytest

from beagle.explain import Explainer
from beagle.explain.flow import build_flow
from beagle.explain.mermaid import render
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

CERT_PY = '''\
import frappe
import subprocess


class Certificate(Document):
    def renew(self):
        if self.attempts >= 5:
            raise MaxAttempts("stop")
        try:
            self._obtain()
        except DNSError:
            self.status = "Failed"
            return False
        frappe.enqueue("app.tasks.notify")
        return True

    def _obtain(self):
        return subprocess.run("certbot renew")
'''


@pytest.fixture
def ws(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "cert.py").write_text(CERT_PY)
    w = Workspace(tmp_path)
    w.index()
    yield w
    w.close()


def _explainer(ws):
    return Explainer(ws.repo, GraphService(ws.repo), ws.read_range)


def test_build_flow_nodes():
    graph = build_flow(CERT_PY, "renew", 6, "app.cert.Certificate.renew")
    kinds = {n.kind for n in graph.nodes}
    assert "branch" in kinds      # if self.attempts >= 5
    assert "raise" in kinds       # raise MaxAttempts
    assert "except" in kinds      # except DNSError
    assert "job" in kinds         # enqueue
    labels = " ".join(n.label for n in graph.nodes)
    assert "attempts" in labels


def test_mermaid_deterministic():
    g1 = build_flow(CERT_PY, "renew", 6, "x")
    g2 = build_flow(CERT_PY, "renew", 6, "x")
    assert render(g1) == render(g2)
    assert render(g1).startswith("flowchart TD")


def test_mermaid_marks_uncertain_except_edge():
    graph = build_flow(CERT_PY, "renew", 6, "x")
    out = render(graph)
    assert "-.->" in out  # the error edge into except is uncertain


def test_explain_summary(ws):
    result = _explainer(ws).explain("Certificate.renew")
    assert result.entity is not None
    text = "\n".join(result.summary)
    assert "raises: MaxAttempts" in text
    assert "handles: DNSError" in text
    assert "enqueues" in text


def test_explain_with_mermaid(ws):
    result = _explainer(ws).explain("Certificate.renew", include_mermaid=True)
    assert result.mermaid and "flowchart TD" in result.mermaid
    assert result.node_sources
    assert all(line > 0 for _, _, line in result.node_sources)


def test_explain_expand_calls(ws):
    result = _explainer(ws).explain("Certificate.renew", include_mermaid=True, expand_calls=1)
    # expanding _obtain should pull in the subprocess command node
    assert "certbot" in result.mermaid or "subprocess" in result.mermaid


def test_explain_ambiguous_returns_candidates(ws):
    result = _explainer(ws).explain("nonexistent_symbol_xyz")
    assert result.entity is None
