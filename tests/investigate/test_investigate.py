from __future__ import annotations

from pathlib import Path

import pytest

from beagle.investigate import Investigator, parse_issue
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
    return Investigator(ws.repo, GraphService(ws.repo), SearchEngine(ws.db), ws.read_range)


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
