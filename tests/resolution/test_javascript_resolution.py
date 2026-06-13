from __future__ import annotations

import json
from pathlib import Path

import pytest

from beagle.workspace import Workspace

API_PY = '''\
import frappe


@frappe.whitelist()
def deploy(name):
    return name


@frappe.whitelist()
def save(name):
    return name
'''

SITE_JSON = {
    "doctype": "DocType", "name": "Site", "module": "App",
    "fields": [{"fieldname": "status", "fieldtype": "Data"}],
}

SITE_JS = '''\
class SiteController extends frappe.ui.form.Controller {
  refresh() {
    frappe.call({ method: "app.api.deploy", args: { name: this.name } });
    frappe.db.get_list("Site", { filters: {} });
  }
  rename() {
    frm.call("rename_site");
  }
}
'''


@pytest.fixture
def ws(tmp_path: Path):
    app = tmp_path / "app"
    (app / "doctype" / "site").mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "api.py").write_text(API_PY)
    (app / "doctype" / "site" / "site.json").write_text(json.dumps(SITE_JSON))
    (app / "public" / "js").mkdir(parents=True)
    (app / "public" / "js" / "site.js").write_text(SITE_JS)
    workspace = Workspace(tmp_path)
    workspace.index()
    yield workspace
    workspace.close()


def edges(ws: Workspace, relationship: str):
    rows = ws.db.conn.execute(
        "SELECT source_id, target_id, resolver, confidence, target_hint "
        "FROM edges WHERE relationship = ?",
        (relationship,),
    ).fetchall()
    return [dict(r) for r in rows]


def test_calls_backend_resolves_to_python_handler(ws):
    calls = edges(ws, "CALLS_BACKEND")
    deploy = next(e for e in calls if e["target_hint"] == "app.api.deploy")
    assert deploy["target_id"] == "python://app.api#deploy"
    assert deploy["resolver"] == "js-backend-call"
    assert deploy["confidence"] == pytest.approx(0.9)
    assert deploy["source_id"].endswith("#SiteController.refresh")


def test_queries_doctype_resolves_by_name(ws):
    queries = edges(ws, "QUERIES_DOCTYPE")
    site = next(e for e in queries if e["target_hint"] == "Site")
    assert site["target_id"] == "doctype://app/Site"
    assert site["resolver"] == "js-doctype-query"


def test_form_local_call_is_unresolved_but_visible(ws):
    calls = edges(ws, "CALLS_BACKEND")
    rename = next(e for e in calls if e["target_hint"] == "rename_site")
    assert rename["target_id"] is None
    assert rename["resolver"] == "unresolved"
