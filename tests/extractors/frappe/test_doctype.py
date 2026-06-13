from __future__ import annotations

import json
from pathlib import Path

import pytest

from beagle.workspace import Workspace

SITE_JSON = {
    "doctype": "DocType",
    "name": "Site",
    "module": "MyApp",
    "fields": [
        {"fieldname": "status", "fieldtype": "Data", "label": "Status"},
        {"fieldname": "team", "fieldtype": "Link", "options": "Team", "label": "Team"},
        {"fieldname": "apps", "fieldtype": "Table", "options": "Site App"},
        {"fieldname": "ref_doc", "fieldtype": "Dynamic Link", "options": "ref_type"},
    ],
}
TEAM_JSON = {"doctype": "DocType", "name": "Team", "module": "MyApp", "fields": []}
SITE_APP_JSON = {
    "doctype": "DocType", "name": "Site App", "module": "MyApp", "istable": 1,
    "fields": [{"fieldname": "app", "fieldtype": "Data"}],
}

SITE_PY = '''\
from frappe.model.document import Document


class Site(Document):
    def deploy(self):
        return 1
'''

TEST_SITE_PY = '''\
class TestSite(FrappeTestCase):
    def test_deploy(self):
        assert True
'''


def _doctype_dir(app_pkg: Path, scrub: str) -> Path:
    d = app_pkg / "doctype" / scrub
    d.mkdir(parents=True)
    return d


@pytest.fixture
def frappe_repo(tmp_path: Path):
    app_pkg = tmp_path / "myapp" / "myapp"
    site = _doctype_dir(app_pkg, "site")
    (site / "site.json").write_text(json.dumps(SITE_JSON))
    (site / "site.py").write_text(SITE_PY)
    (site / "test_site.py").write_text(TEST_SITE_PY)
    team = _doctype_dir(app_pkg, "team")
    (team / "team.json").write_text(json.dumps(TEAM_JSON))
    child = _doctype_dir(app_pkg, "site_app")
    (child / "site_app.json").write_text(json.dumps(SITE_APP_JSON))
    ws = Workspace(tmp_path)
    ws.index()
    yield ws
    ws.close()


def edges(ws, relationship):
    rows = ws.db.conn.execute(
        "SELECT source_id, target_id, resolver, confidence FROM edges WHERE relationship=?",
        (relationship,),
    ).fetchall()
    return [(r["source_id"], r["target_id"], r["resolver"], r["confidence"]) for r in rows]


def test_doctype_and_field_entities(frappe_repo):
    assert frappe_repo.repo.get_entity("doctype://myapp/Site") is not None
    field = frappe_repo.repo.get_entity("doctype-field://myapp/Site#status")
    assert field is not None and field.extra["fieldtype"] == "Data"


def test_has_field(frappe_repo):
    assert any(
        s == "doctype://myapp/Site" and t == "doctype-field://myapp/Site#team"
        for s, t, _, _ in edges(frappe_repo, "HAS_FIELD")
    )


def test_link_field_resolves(frappe_repo):
    assert any(
        s == "doctype-field://myapp/Site#team" and t == "doctype://myapp/Team"
        for s, t, _, _ in edges(frappe_repo, "LINKS_TO")
    )


def test_table_field_contains_child(frappe_repo):
    assert any(
        s == "doctype://myapp/Site" and t == "doctype://myapp/Site App"
        for s, t, _, _ in edges(frappe_repo, "CONTAINS_CHILD")
    )


def test_dynamic_link_preserved_unresolved(frappe_repo):
    rows = edges(frappe_repo, "LINKS_TO")
    assert any(
        s == "doctype-field://myapp/Site#ref_doc" and t is None
        and resolver == "frappe-dynamic-link"
        for s, t, resolver, _ in rows
    )


def test_has_controller(frappe_repo):
    rows = edges(frappe_repo, "HAS_CONTROLLER")
    assert any(
        s == "doctype://myapp/Site" and t.endswith("#Site") for s, t, _, _ in rows
    )


def test_tests_edge(frappe_repo):
    rows = edges(frappe_repo, "TESTS")
    assert any(
        s.endswith("#TestSite") and t == "doctype://myapp/Site" for s, t, _, _ in rows
    )
