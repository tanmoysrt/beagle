from __future__ import annotations

from pathlib import Path

import pytest

from beagle.card import ContextCardBuilder, as_dict, render, render_card_mermaid
from beagle.card.classify import action_verb, call_category, external_boundary
from beagle.lifecycle import LifecycleService
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

SITE_PY = '''\
import frappe
import subprocess


class Site(Document):
    @frappe.whitelist()
    def deactivate(self):
        if self.status not in ("Active", "Broken"):
            frappe.throw("Cannot deactivate")
        if self.attempts >= 3:
            raise TooMany("stop")
        self.status = "Inactive"
        self.update_proxy()
        self.save()

    def update_proxy(self):
        return subprocess.run("agent proxy --update", shell=True)
'''

TASKS_PY = '''\
import frappe


def sweep_sites():
    site = frappe.get_doc("Site", "x")
    site.deactivate()
'''

HOOKS_PY = 'scheduler_events = {"daily": ["app.tasks.sweep_sites"]}\n'


@pytest.fixture
def ws(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hooks.py").write_text(HOOKS_PY)
    (pkg / "tasks.py").write_text(TASKS_PY)
    dt = pkg / "doctype" / "site"
    dt.mkdir(parents=True)
    (pkg / "doctype" / "__init__.py").write_text("")
    (dt / "__init__.py").write_text("")
    (dt / "site.py").write_text(SITE_PY)
    (dt / "site.json").write_text(
        '{"doctype":"DocType","name":"Site","module":"App",'
        '"fields":[{"fieldname":"status","fieldtype":"Data"},'
        '{"fieldname":"attempts","fieldtype":"Int"}]}'
    )
    w = Workspace(tmp_path)
    w.index()
    yield w
    w.close()


def _builder(ws, with_lifecycle=True):
    graph = GraphService(ws.repo)
    lifecycle = LifecycleService(ws.repo, graph) if with_lifecycle else None
    return ContextCardBuilder(ws.repo, graph, ws.read_range, lifecycle)


# --- classify ---------------------------------------------------------

def test_action_verb_takes_first_token():
    assert action_verb("deactivate") == "deactivate"
    assert action_verb("retry_failed_certificates") == "retry"
    assert action_verb("_private_helper") == "private"


def test_external_boundary_detects_shell():
    kind, detail = external_boundary({"dotted": "subprocess.run", "first_arg": "certbot renew"})
    assert kind == "shell" and "certbot" in detail


def test_call_category_ignores_trivial():
    assert call_category({"dotted": "len"}) is None
    assert call_category({"head": "self", "attr": "save"}) == "business"
    assert call_category({"dotted": "frappe.enqueue"}) == "job"


# --- build ------------------------------------------------------------

def test_identity_and_signature(ws):
    card = _builder(ws).build("Site.deactivate")
    assert card.identity.qualified_name.endswith("Site.deactivate")
    assert card.identity.kind == "method"
    assert "deactivate" in card.identity.signature


def test_guards_capture_threshold_and_throw(ws):
    card = _builder(ws).build("Site.deactivate")
    kinds = {g.kind for g in card.guards}
    assert "threshold" in kinds  # attempts >= 3
    assert "throw" in kinds      # frappe.throw
    assert any("whitelist" in g.text for g in card.guards if g.kind == "decorator")


def test_state_changes_include_status_write_and_save(ws):
    card = _builder(ws).build("Site.deactivate")
    kinds = {w.kind for w in card.writes}
    assert "status-write" in kinds
    assert "saves" in kinds  # self.save() -> SAVES_DOCTYPE


def test_entrypoint_is_endpoint(ws):
    card = _builder(ws).build("Site.deactivate")
    assert any(e.kind == "endpoint" for e in card.entrypoints)


def test_external_boundary_surfaced_via_callee(ws):
    card = _builder(ws).build("Site.update_proxy")
    assert any(b.kind == "shell" and "agent" in b.detail for b in card.external_boundaries)


def test_failures_capture_raise(ws):
    card = _builder(ws).build("Site.deactivate")
    assert any(f.kind == "raises" and f.detail == "TooMany" for f in card.failures)
    assert any(f.kind == "throws" for f in card.failures)


def test_lifecycle_expanded_for_save(ws):
    card = _builder(ws).build("Site.deactivate")
    assert any(p.operation == "saves" and p.doctype == "Site" and "validate" in p.events
               for p in card.lifecycle)


def test_lifecycle_omitted_without_service(ws):
    card = _builder(ws, with_lifecycle=False).build("Site.deactivate")
    assert card.lifecycle == []


def test_responsibility_inferred_with_evidence(ws):
    card = _builder(ws).build("Site.deactivate")
    assert card.responsibility.action == "deactivate"
    assert card.responsibility.confidence >= 0.4
    assert any("method name" in e for e in card.responsibility.evidence)


def test_unknowns_report_missing_tests(ws):
    card = _builder(ws).build("Site.deactivate")
    assert any("test" in u for u in card.unknowns)


def test_ambiguous_returns_candidates(ws):
    card = _builder(ws).build("nonexistent_symbol_zzz")
    assert card is None


# --- render -----------------------------------------------------------

def test_compact_dict_has_all_sections(ws):
    data = as_dict(_builder(ws).build("Site.deactivate"))
    for key in ("identity", "responsibility", "entrypoints", "guards", "writes",
                "calls", "lifecycle", "external_boundaries", "failures", "unknowns"):
        assert key in data


def test_text_render_keeps_unknowns_under_tight_budget(ws):
    lines = render(_builder(ws).build("Site.deactivate"), max_tokens=40)
    text = "\n".join(lines)
    assert "Unknowns" in text  # never dropped for budget


def test_mermaid_is_deterministic_and_capped(ws):
    card = _builder(ws).build("Site.deactivate")
    out1 = render_card_mermaid(card)
    out2 = render_card_mermaid(card)
    assert out1 == out2
    assert out1.startswith("flowchart TD")
    assert "-.->" in out1  # dashed lifecycle/boundary edge
