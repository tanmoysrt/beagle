from __future__ import annotations

import json
from pathlib import Path

import pytest

from beagle.workspace import Workspace

SITE_JSON = {"doctype": "DocType", "name": "Site", "module": "MyApp", "fields": []}

API_PY = '''\
import frappe


@frappe.whitelist()
def get_site(name):
    site = frappe.get_doc("Site", name)
    frappe.db.set_value("Site", name, "status", "Active")
    frappe.enqueue("myapp.tasks.poll_site", name=name)
    return site


def new_site():
    return frappe.new_doc("Site")
'''

TASKS_PY = '''\
def poll_site(name=None):
    return name
'''

HOOKS_PY = '''\
app_name = "myapp"

doc_events = {
    "Site": {
        "on_update": "myapp.tasks.poll_site",
        "validate": ["myapp.tasks.poll_site"],
    }
}

scheduler_events = {
    "daily": ["myapp.tasks.poll_site"],
}

override_doctype_class = {
    "Site": "myapp.overrides.CustomSite",
}
'''

OVERRIDES_PY = '''\
class CustomSite:
    pass
'''


@pytest.fixture
def app(tmp_path: Path):
    pkg = tmp_path / "myapp" / "myapp"
    (pkg.parent).mkdir()
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hooks.py").write_text(HOOKS_PY)
    (pkg / "api.py").write_text(API_PY)
    (pkg / "tasks.py").write_text(TASKS_PY)
    (pkg / "overrides.py").write_text(OVERRIDES_PY)
    site = pkg / "doctype" / "site"
    site.mkdir(parents=True)
    (site / "site.json").write_text(json.dumps(SITE_JSON))
    ws = Workspace(tmp_path)
    ws.index()
    yield ws
    ws.close()


def edges(ws, relationship):
    rows = ws.db.conn.execute(
        "SELECT source_id, target_id, resolver FROM edges WHERE relationship=?",
        (relationship,),
    ).fetchall()
    return [(r["source_id"], r["target_id"], r["resolver"]) for r in rows]


def test_endpoint_entity_and_edge(app):
    assert app.repo.get_entity("endpoint://myapp.api.get_site") is not None
    assert any(
        s == "python://myapp.api#get_site" and t == "endpoint://myapp.api.get_site"
        for s, t, _ in edges(app, "EXPOSES_ENDPOINT")
    )


def test_orm_reads_and_writes(app):
    reads = edges(app, "READS_DOCTYPE")
    writes = edges(app, "WRITES_DOCTYPE")
    creates = edges(app, "CREATES_DOCTYPE")
    assert any(t == "doctype://myapp/Site" for _, t, _ in reads)
    assert any(t == "doctype://myapp/Site" for _, t, _ in writes)
    assert any(t == "doctype://myapp/Site" for _, t, _ in creates)


def test_enqueue_job_and_invokes(app):
    assert app.repo.get_entity("job://myapp.tasks.poll_site") is not None
    enq = edges(app, "ENQUEUES")
    assert any(t == "job://myapp.tasks.poll_site" for _, t, _ in enq)
    invokes = edges(app, "INVOKES")
    assert any(
        s == "job://myapp.tasks.poll_site" and t == "python://myapp.tasks#poll_site"
        for s, t, _ in invokes
    )


def test_doc_event_hook(app):
    invokes = edges(app, "INVOKES")
    assert any(
        s == "doctype://myapp/Site" and t == "python://myapp.tasks#poll_site"
        and resolver == "frappe-doc-event"
        for s, t, resolver in invokes
    )


def test_scheduler_hook(app):
    invokes = edges(app, "INVOKES")
    assert any(
        t == "python://myapp.tasks#poll_site" and resolver == "frappe-scheduler"
        for _, t, resolver in invokes
    )


def test_override_doctype_class(app):
    controllers = edges(app, "HAS_CONTROLLER")
    assert any(
        s == "doctype://myapp/Site" and t == "python://myapp.overrides#CustomSite"
        and resolver == "frappe-override-class"
        for s, t, resolver in controllers
    )
