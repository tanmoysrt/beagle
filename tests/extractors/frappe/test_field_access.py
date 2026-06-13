from __future__ import annotations

import json
from pathlib import Path

import pytest

from beagle.workspace import Workspace

CERT_JSON = {
    "doctype": "DocType", "name": "TLS Certificate", "module": "App",
    "fields": [{"fieldname": "attempts", "fieldtype": "Int"},
               {"fieldname": "status", "fieldtype": "Data"}],
}

CERT_PY = '''\
import frappe
from frappe.model.document import Document


class TLSCertificate(Document):
    def renew(self):
        if self.attempts >= 5:        # field READ in a condition
            return
        self.status = "Renewing"      # field WRITE

    def peek(self):
        return frappe.db.get_value("TLS Certificate", self.name, "status")
'''


@pytest.fixture
def ws(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    cert = pkg / "doctype" / "tls_certificate"
    cert.mkdir(parents=True)
    (cert / "__init__.py").write_text("")
    (cert / "tls_certificate.json").write_text(json.dumps(CERT_JSON))
    (cert / "tls_certificate.py").write_text(CERT_PY)
    w = Workspace(tmp_path)
    w.index()
    yield w
    w.close()


def readers(ws, field_id):
    return {(e.source_id.split("#")[-1], e.resolver)
            for e in ws.repo.edges_to(field_id, ("READS_FIELD",))}


ATTEMPTS = "doctype-field://app/TLS Certificate#attempts"
STATUS = "doctype-field://app/TLS Certificate#status"


def test_self_field_comparison_is_a_field_read(ws):
    assert ("TLSCertificate.renew", "frappe-field-read") in readers(ws, ATTEMPTS)


def test_getvalue_field_arg_is_a_field_read(ws):
    assert ("TLSCertificate.peek", "frappe-field-read") in readers(ws, STATUS)


def test_field_write_is_not_a_read(ws):
    # self.status = ... is a WRITES_FIELD, must never appear as a READS_FIELD
    assert not any(src == "TLSCertificate.renew" for src, _ in readers(ws, STATUS))
    writes = {e.source_id.split("#")[-1]
              for e in ws.repo.edges_to(STATUS, ("WRITES_FIELD",))}
    assert "TLSCertificate.renew" in writes
