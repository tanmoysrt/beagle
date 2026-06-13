from __future__ import annotations

from pathlib import Path

import pytest

from beagle.investigate import Investigator, parse_issue, render_investigation
from beagle.lifecycle import LifecycleService
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

CERT_PY = '''\
import frappe
import subprocess


class Certificate(Document):
    def renew(self):
        if self.attempts >= 5:
            frappe.throw("Max renewal attempts reached")
            return
        try:
            self.run_certbot()
        except DNSValidationError:
            self.status = "DNS Failed"
        except RateLimitError:
            self.status = "Rate Limited"
        self.attempts += 1
        self.save()

    def run_certbot(self):
        return subprocess.run("certbot renew --force", shell=True)
'''

TASKS_PY = '''\
import frappe


def retry_failed_certificates():
    cert = frappe.get_doc("TLS Certificate", "abc")
    cert.renew()
'''

HOOKS_PY = '''\
scheduler_events = {"hourly": ["app.tasks.retry_failed_certificates"]}
'''


@pytest.fixture
def repo(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hooks.py").write_text(HOOKS_PY)
    (pkg / "tasks.py").write_text(TASKS_PY)
    (pkg / "doctype").mkdir()
    (pkg / "doctype" / "__init__.py").write_text("")
    cert = pkg / "doctype" / "tls_certificate"
    cert.mkdir(parents=True)
    (cert / "__init__.py").write_text("")
    (cert / "tls_certificate.py").write_text(CERT_PY)
    (cert / "tls_certificate.json").write_text(
        '{"doctype":"DocType","name":"TLS Certificate","module":"App",'
        '"fields":[{"fieldname":"attempts","fieldtype":"Int"},'
        '{"fieldname":"status","fieldtype":"Data"}]}'
    )
    ws = Workspace(tmp_path)
    ws.index()
    yield ws
    ws.close()


def _investigator(ws):
    graph = GraphService(ws.repo)
    return Investigator(ws.repo, graph, SearchEngine(ws.db), ws.read_range,
                        LifecycleService(ws.repo, graph))


def section(report, title):
    return next(s for s in report.sections if s.title == title)


def test_parse_issue_keeps_numbers_and_drops_generic():
    q = parse_issue("certificate renewal stops after 5 attempts due to DNS")
    assert "5" in q.numbers
    assert "renewal" in q.terms or "certificate" in q.terms
    assert "attempts" not in q.terms  # generic
    assert "status" not in q.terms


def test_renew_is_top_seed(repo):
    report = _investigator(repo).investigate(
        "Certificate renewal stops after 5 attempts; DNS and rate limit failures"
    )
    assert report.cited
    assert report.cited[0][0] == "python://app.doctype.tls_certificate.tls_certificate#Certificate.renew"


def test_retry_conditions_detected(repo):
    report = _investigator(repo).investigate("renewal stops after 5 attempts")
    lines = " ".join(section(report, "Retry and stop conditions").lines)
    assert "self.attempts" in lines
    assert "5" in lines


def test_failure_handling_detected(repo):
    report = _investigator(repo).investigate("DNS validation and rate limit failures in renewal")
    lines = " ".join(section(report, "Failure handling").lines)
    assert "DNSValidationError" in lines
    assert "RateLimitError" in lines


def test_external_command_detected(repo):
    report = _investigator(repo).investigate("certbot renewal fails")
    lines = " ".join(section(report, "External systems and commands").lines)
    assert "certbot" in lines or "subprocess" in lines


def test_entrypoint_detected(repo):
    report = _investigator(repo).investigate("retry certificate renewal scheduled job")
    lines = " ".join(section(report, "Primary entrypoints").lines)
    assert "retry_failed_certificates" in lines


def test_source_ranges_present(repo):
    report = _investigator(repo).investigate("certificate renewal 5 attempts")
    assert section(report, "Source ranges").lines


# --- design/11 additions ---------------------------------------------

def test_query_expansion_is_small_and_separate():
    q = parse_issue("certificate renewal fails")
    # renewal -> renew via curated synonym; variants never pollute concept terms
    assert "renew" in q.expansions
    assert "renewal" in q.terms
    assert not (q.terms & q.expansions)


def test_structured_result_has_section_12_keys(repo):
    report = _investigator(repo).investigate("certificate renewal stops after 5 attempts")
    data = report.data
    for key in ("query", "primary_workflows", "conditions", "state_changes",
                "external_boundaries", "framework_events", "tests",
                "change_points", "unknowns", "sources"):
        assert key in data
    assert data["sources"] and "score" in data["sources"][0]


def test_framework_lifecycle_expanded_for_save(repo):
    report = _investigator(repo).investigate("certificate renewal saves the document")
    events = report.data["framework_events"]
    # Certificate.renew calls self.save() -> implicit lifecycle on TLS Certificate
    assert any(fw["doctype"] == "TLS Certificate" and "validate" in fw["events"]
               for fw in events)
    lines = " ".join(section(report, "Framework lifecycle").lines)
    assert "on_change" in lines


def test_workflow_start_is_labelled_entrypoint(repo):
    report = _investigator(repo).investigate("certificate renewal stops after 5 attempts")
    steps = report.data["primary_workflows"][0]["steps"]
    assert steps[0]["via"] == "entrypoint"


def test_next_hop_labels_resolved_call_and_lifecycle(repo):
    # Certificate.renew calls self.run_certbot() (resolved -> "call") and
    # self.save() (operation -> "lifecycle: saves"). Hop labels reflect type.
    inv = _investigator(repo)
    renew = "python://app.doctype.tls_certificate.tls_certificate#Certificate.renew"
    assert inv._next_hop(renew, set()) == (
        "python://app.doctype.tls_certificate.tls_certificate#Certificate.run_certbot", "call")
    # with the call target already visited, the next hop is the save lifecycle
    seen = {renew, "python://app.doctype.tls_certificate.tls_certificate#Certificate.run_certbot"}
    target, via = inv._next_hop(renew, seen)
    assert target == "doctype://app/TLS Certificate" and via == "lifecycle: saves"


def test_mermaid_renders_from_evidence(repo):
    report = _investigator(repo).investigate("certificate renewal stops after 5 attempts")
    diagram = render_investigation(report.data)
    assert diagram.startswith("flowchart TD")
    assert diagram.count("\n") <= 60  # compact, node-capped


def test_lifecycle_omitted_without_service(repo):
    graph = GraphService(repo.repo)
    inv = Investigator(repo.repo, graph, SearchEngine(repo.db), repo.read_range)
    report = inv.investigate("certificate renewal saves the document")
    assert report.data["framework_events"] == []
