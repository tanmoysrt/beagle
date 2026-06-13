"""Detect Frappe document persistence operations (design/08).

Resolves the receiver DocType of ``doc.save()`` / ``.insert()`` / ``.submit()``
/ ``.cancel()`` / ``.delete()`` / ``.db_set()`` / ``.discard()`` and
``frappe.delete_doc(...)`` / ``doc.run_method("evt")``, then emits operation
edges (SAVES_DOCTYPE, INSERTS_DOCTYPE, ...). Lifecycle expansion is left to the
policy/dispatcher at query time.

Conservative: an operation edge is emitted only when the receiver DocType is
resolved (literal ``get_doc``/``new_doc`` or controller ``self``). Direct DB
writes (``frappe.db.set_value``/``db.delete``/``db_update``) are NOT operations
and never trigger lifecycle expansion.
"""

from __future__ import annotations

from beagle.models import Edge, Observation
from beagle.resolution.calls import RESOLVER_VERSION
from beagle.resolution.symbols import SymbolTable

# method name -> operation relationship
_OP_METHODS = {
    "insert": "INSERTS_DOCTYPE",
    "save": "SAVES_DOCTYPE",
    "submit": "SUBMITS_DOCTYPE",
    "cancel": "CANCELS_DOCTYPE",
    "delete": "DELETES_DOCTYPE",
    "db_set": "DB_SETS_DOCTYPE",
    "discard": "DISCARDS_DOCTYPE",
}
# value-call constructors that bind a variable to a DocType
_DOC_CONSTRUCTORS = {
    "frappe.get_doc", "frappe.new_doc", "frappe.get_last_doc",
    "frappe.get_cached_doc", "frappe.get_single",
}
_SELF = ("self", "cls")


def operation_edges(
    repo, table: SymbolTable, by_name: dict[str, str], class_to_doctype: dict[str, str]
) -> list[Edge]:
    var_types = _variable_types(repo, by_name)
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("call"):
        edges += _edges_for_call(obs, table, by_name, class_to_doctype, var_types)
    return edges


def _variable_types(repo, by_name: dict[str, str]) -> dict[str, dict[str, str]]:
    """subject -> {variable_code: doctype_id} from literal get_doc/new_doc binds."""
    out: dict[str, dict[str, str]] = {}
    for obs in repo.observations_of_kind("assignment"):
        if obs.data.get("value_callee") in _DOC_CONSTRUCTORS:
            doctype = by_name.get(obs.data.get("value_first_arg") or "")
            if doctype:
                out.setdefault(obs.subject, {})[obs.data.get("target_code")] = doctype
    return out


def _edges_for_call(obs, table, by_name, class_to_doctype, var_types) -> list[Edge]:
    data = obs.data
    if data.get("dotted") == "frappe.delete_doc":
        return _delete_doc_edge(obs, by_name)
    attr = data.get("attr")
    receiver = data.get("receiver_code")
    if not attr or not receiver:
        return []
    if attr == "run_method":
        return _run_method_edge(obs, table, class_to_doctype, var_types)
    relationship = _OP_METHODS.get(attr)
    if not relationship:
        return []
    doctype, confidence, evidence = _receiver_doctype(
        obs, receiver, table, class_to_doctype, var_types
    )
    if not doctype:
        return []
    return [_op_edge(obs, relationship, doctype, confidence,
                     {"method": attr, **evidence})]


def _receiver_doctype(obs, receiver, table, class_to_doctype, var_types):
    if receiver in _SELF:
        cls = table.class_of(obs.subject)
        doctype = class_to_doctype.get(cls) if cls else None
        return doctype, 0.9, {"receiver": "self-controller"}
    doctype = var_types.get(obs.subject, {}).get(receiver)
    return doctype, 0.95, {"receiver": receiver}


def _delete_doc_edge(obs, by_name) -> list[Edge]:
    args = obs.data.get("string_args") or []
    doctype = by_name.get(args[0]) if args and args[0] else None
    if not doctype:
        return []
    return [_op_edge(obs, "DELETES_DOCTYPE", doctype, 0.95,
                     {"method": "frappe.delete_doc", "receiver": "literal"})]


def _run_method_edge(obs, table, class_to_doctype, var_types) -> list[Edge]:
    args = obs.data.get("string_args") or []
    event = args[0] if args and args[0] else None
    if not event:
        return []
    doctype, confidence, _ = _receiver_doctype(
        obs, obs.data.get("receiver_code"), table, class_to_doctype, var_types
    )
    if not doctype:
        return []
    return [_op_edge(obs, "RUNS_EVENT", doctype, confidence,
                     {"method": "run_method", "event": event})]


def _op_edge(obs: Observation, relationship, doctype, confidence, evidence) -> Edge:
    return Edge(
        source_id=obs.subject,
        relationship=relationship,
        target_id=doctype,
        confidence=confidence,
        resolver="frappe-operation",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence=evidence,
    )
