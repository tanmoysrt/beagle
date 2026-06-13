from __future__ import annotations

import json
from pathlib import Path

import pytest

from beagle.lifecycle import LifecycleService
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

HOOKS = '''\
doc_events = {
    "Order": {
        "validate": "app.events.exact_validate",
        "on_update": "app.events.exact_handler",
    },
    "*": {
        "on_update": ["app.events.wildcard_handler"],
    },
}
override_doctype_class = {"Invoice": "app.overrides.CustomInvoice"}
extend_doctype_class = {"Order": "app.overrides.OrderMixin"}
'''

EVENTS = '''\
def exact_validate(doc, method=None):
    return doc


def exact_handler(doc, method=None):
    return doc


def wildcard_handler(doc, method=None):
    return doc
'''

OVERRIDES = '''\
class CustomInvoice:
    def on_update(self):
        return 1


class OrderMixin:
    def on_update(self):
        return super().on_update()
'''

API = '''\
import frappe


def place_order(name):
    order = frappe.get_doc("Order", name)
    order.status = "Placed"
    order.save()
    inv = frappe.new_doc("Invoice")
    inv.insert()
    frappe.db.set_value("Order", name, "amount", 1)
    frappe.enqueue("app.tasks.reprocess", name=name)


def cancel_order(name):
    order = frappe.get_doc("Order", name)
    order.cancel()


def remove(name):
    frappe.delete_doc("Order", name)
'''

TASKS = '''\
import frappe


def reprocess(name=None):
    order = frappe.get_doc("Order", name)
    order.submit()
    order.run_method("recompute_totals")
'''

ORDER_PY = '''\
from frappe.model.document import Document


class Order(Document):
    def validate(self):
        self.status = "Validated"

    def on_update(self):
        return 1

    def touch(self):
        self.db_set("status", "Touched")
'''

ORDER_LINE_PY = '''\
from frappe.model.document import Document


class OrderLine(Document):
    def on_update(self):
        return 1
'''

INVOICE_PY = '''\
from frappe.model.document import Document


class Invoice(Document):
    pass
'''


def _doctype(pkg, scrub, name, fields, controller, istable=0):
    d = pkg / "doctype" / scrub
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    (d / f"{scrub}.json").write_text(json.dumps(
        {"doctype": "DocType", "name": name, "module": "App", "istable": istable, "fields": fields}
    ))
    (d / f"{scrub}.py").write_text(controller)


@pytest.fixture
def ws(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "doctype").mkdir()
    (pkg / "doctype" / "__init__.py").write_text("")
    (pkg / "hooks.py").write_text(HOOKS)
    (pkg / "events.py").write_text(EVENTS)
    (pkg / "overrides.py").write_text(OVERRIDES)
    (pkg / "api.py").write_text(API)
    (pkg / "tasks.py").write_text(TASKS)
    _doctype(pkg, "order", "Order",
             [{"fieldname": "status", "fieldtype": "Data"},
              {"fieldname": "lines", "fieldtype": "Table", "options": "Order Line"}],
             ORDER_PY)
    _doctype(pkg, "order_line", "Order Line",
             [{"fieldname": "qty", "fieldtype": "Int"}], ORDER_LINE_PY, istable=1)
    _doctype(pkg, "invoice", "Invoice", [], INVOICE_PY)
    w = Workspace(tmp_path)
    w.index()
    yield w
    w.close()


def op_edges(ws, rel):
    rows = ws.db.conn.execute(
        "SELECT source_id, target_id FROM edges WHERE relationship=?", (rel,)
    ).fetchall()
    return {(r["source_id"].split("#")[-1], r["target_id"]) for r in rows}


def _service(ws):
    return LifecycleService(ws.repo, GraphService(ws.repo))


# --- operation detection ----------------------------------------------

def test_saves_and_inserts(ws):
    assert ("place_order", "doctype://app/Order") in op_edges(ws, "SAVES_DOCTYPE")
    assert ("place_order", "doctype://app/Invoice") in op_edges(ws, "INSERTS_DOCTYPE")


def test_cancel_submit_delete_detected(ws):
    assert ("cancel_order", "doctype://app/Order") in op_edges(ws, "CANCELS_DOCTYPE")
    assert ("reprocess", "doctype://app/Order") in op_edges(ws, "SUBMITS_DOCTYPE")
    assert ("remove", "doctype://app/Order") in op_edges(ws, "DELETES_DOCTYPE")


def test_db_set_method_is_operation_not_save(ws):
    assert ("Order.touch", "doctype://app/Order") in op_edges(ws, "DB_SETS_DOCTYPE")


def test_run_method_literal(ws):
    assert ("reprocess", "doctype://app/Order") in op_edges(ws, "RUNS_EVENT")


# --- critical negatives -----------------------------------------------

def test_direct_set_value_is_not_an_operation(ws):
    # place_order calls frappe.db.set_value("Order", ...): a direct write, not a
    # document operation. It SAVES Order (via .save()) but must never DB_SET it.
    assert ("place_order", "doctype://app/Order") in op_edges(ws, "SAVES_DOCTYPE")
    assert ("place_order", "doctype://app/Order") not in op_edges(ws, "DB_SETS_DOCTYPE")


def test_no_child_row_operation_from_parent(ws):
    # nothing saves Order Line; parent save must not invent child lifecycle
    for rel in ("SAVES_DOCTYPE", "INSERTS_DOCTYPE", "DB_SETS_DOCTYPE"):
        assert not any(t == "doctype://app/Order Line" for _, t in op_edges(ws, rel))


# --- event dispatch ---------------------------------------------------

def test_event_handlers_controller_via_extend_mro(ws):
    dispatch = _service(ws).event_handlers("Order", "on_update")
    # OrderMixin (extend_doctype_class) comes first in the MRO
    assert dispatch.controller.target_id == "python://app.overrides#OrderMixin.on_update"


def test_event_handlers_exact_and_wildcard(ws):
    dispatch = _service(ws).event_handlers("Order", "on_update")
    exact = {h.target_id for h in dispatch.exact}
    wildcard = {h.target_id for h in dispatch.wildcard}
    assert "python://app.events#exact_handler" in exact
    assert "python://app.events#wildcard_handler" in wildcard


def test_event_handlers_runtime_channels_reported(ws):
    dispatch = _service(ws).event_handlers("Order", "on_update")
    channels = {h.hint for h in dispatch.runtime}
    assert {"Notification", "Webhook", "Server Script"} <= channels
    assert any("runtime" in n for n in dispatch.notes)


def test_override_doctype_class_uncertain(ws):
    dispatch = _service(ws).event_handlers("Invoice", "on_update")
    # base Invoice + override CustomInvoice => effective controller uncertain
    assert dispatch.controller.target_id == "python://app.overrides#CustomInvoice.on_update"
    assert dispatch.controller.confidence < 0.99


# --- trace ------------------------------------------------------------

def test_trace_save_to_handler(ws):
    graph = _service(ws).trace("place_order", depth=1)
    cats = {(graph.nodes[s][1], graph.nodes[d][1], c) for s, d, c in graph.edges
            if s in graph.nodes and d in graph.nodes}
    assert ("function", "doctype", "operation") in cats   # place_order -> Order
    assert any(c == "framework" for _, _, c in cats)       # Order -> event / handler


def test_lifecycle_report_save_events(ws):
    report = _service(ws).lifecycle("Order")
    save = next(op for op in report.operations if op.relationship == "SAVES_DOCTYPE")
    seq = [ev.event.name for ev in save.events]
    assert seq == ["before_validate", "validate", "before_save", "db_update", "on_update", "on_change"]
