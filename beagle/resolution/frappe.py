"""Resolve Frappe schema observations into edges.

Covers HAS_FIELD, LINKS_TO, CONTAINS_CHILD, HAS_CONTROLLER, and TESTS. Link and
table targets are deterministic DocType-name lookups (high confidence). Dynamic
Link fields are emitted as unresolved edges so the relationship is visible
without committing to a single target.
"""

from __future__ import annotations

import re
from typing import Optional

from beagle.database.repository import Repository
from beagle.models import Edge, Entity
from beagle.resolution.calls import RESOLVER_VERSION
from beagle.resolution.operations import operation_edges
from beagle.resolution.symbols import SymbolTable

_CLASS_KINDS = ("class", "test_class")

# Frappe ORM calls whose first string argument names a DocType.
_ORM_OPS = {
    "frappe.get_doc": "READS_DOCTYPE",
    "frappe.get_cached_doc": "READS_DOCTYPE",
    "frappe.get_last_doc": "READS_DOCTYPE",
    "frappe.get_all": "READS_DOCTYPE",
    "frappe.get_list": "READS_DOCTYPE",
    "frappe.get_value": "READS_DOCTYPE",
    "frappe.db.get_value": "READS_DOCTYPE",
    "frappe.db.get_values": "READS_DOCTYPE",
    "frappe.db.get_all": "READS_DOCTYPE",
    "frappe.db.get_list": "READS_DOCTYPE",
    "frappe.db.get_single_value": "READS_DOCTYPE",
    "frappe.db.exists": "READS_DOCTYPE",
    "frappe.db.count": "READS_DOCTYPE",
    "frappe.new_doc": "CREATES_DOCTYPE",
    "frappe.db.set_value": "WRITES_DOCTYPE",
    "frappe.delete_doc": "DELETES_DOCTYPE",
    "frappe.db.delete": "DELETES_DOCTYPE",
}


def frappe_edges(repo: Repository, table: SymbolTable) -> list[Edge]:
    by_name = _doctype_by_name(table)
    edges: list[Edge] = []
    edges += _has_field_edges(table)
    edges += _field_target_edges(repo, by_name)
    controller_edges, class_to_doctype = _controller_and_test_edges(repo, by_name)
    edges += controller_edges
    edges += _orm_edges(repo, by_name)
    edges += _endpoint_edges(repo)
    edges += _enqueue_edges(repo, table)
    edges += _hook_edges(repo, table, by_name)
    edges += _field_write_edges(repo, table, by_name, class_to_doctype)
    edges += operation_edges(repo, table, by_name, class_to_doctype)
    return edges


def field_id_from_doctype(doctype_id: str, field: str) -> str:
    rest = doctype_id[len("doctype://"):]
    return f"doctype-field://{rest}#{field}"


# ORM reads whose 3rd positional string arg names the field(s) read.
_GETVALUE_FIELD = {"frappe.db.get_value", "frappe.get_value", "frappe.db.get_values"}
# self.<field> with no nested attribute/subscript.
_SELF_FIELD = re.compile(r"^self\.([A-Za-z_]\w*)$")


def _field_write_edges(repo, table, by_name, class_to_doctype) -> list[Edge]:
    edges: list[Edge] = []
    edges += _setvalue_field_edges(repo, table, by_name)
    edges += _self_field_edges(repo, table, class_to_doctype)
    edges += _field_read_edges(repo, table, by_name, class_to_doctype)
    return edges


def _setvalue_field_edges(repo, table, by_name) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("call"):
        if obs.data.get("dotted") != "frappe.db.set_value":
            continue
        args = obs.data.get("string_args") or []
        if len(args) < 3 or not args[0] or not args[2]:
            continue
        doctype = by_name.get(args[0])
        if not doctype:
            continue
        edges.append(_field_edge(obs, obs.subject, doctype, args[2], table, "WRITES_FIELD"))
    return edges


def _self_field_edges(repo, table, class_to_doctype) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("assignment"):
        target = obs.data.get("target_code") or ""
        if not target.startswith("self."):
            continue
        field = target[5:]
        if not field or "." in field or "[" in field:  # nested/subscript, not a direct field
            continue
        cls = table.class_of(obs.subject)
        doctype = class_to_doctype.get(cls) if cls else None
        if doctype:
            edges.append(_field_edge(obs, obs.subject, doctype, field, table, "WRITES_FIELD"))
    return edges


def _field_read_edges(repo, table, by_name, class_to_doctype) -> list[Edge]:
    """Field-level READS_FIELD from two conservative static sources: ORM
    get_value-family field args, and self.<field> reads captured in numeric
    comparison observations (the retry/threshold conditions investigate needs).
    Plain assignment-RHS reads are not tracked — capturing every self.<attr>
    read would inflate the index without a demonstrated need."""
    edges: list[Edge] = []
    edges += _getvalue_field_edges(repo, table, by_name)
    edges += _comparison_field_edges(repo, table, class_to_doctype)
    return edges


def _getvalue_field_edges(repo, table, by_name) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("call"):
        if obs.data.get("dotted") not in _GETVALUE_FIELD:
            continue
        args = obs.data.get("string_args") or []
        doctype = by_name.get(args[0]) if args and args[0] else None
        if not doctype or len(args) < 3 or not args[2]:
            continue
        edges.append(_field_edge(obs, obs.subject, doctype, args[2], table, "READS_FIELD"))
    return edges


def _comparison_field_edges(repo, table, class_to_doctype) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("comparison"):
        match = _SELF_FIELD.match(obs.data.get("left_code") or "")
        if not match:
            continue
        cls = table.class_of(obs.subject)
        doctype = class_to_doctype.get(cls) if cls else None
        if doctype:
            edges.append(_field_edge(obs, obs.subject, doctype, match.group(1), table, "READS_FIELD"))
    return edges


def _field_edge(obs, source, doctype_id, field, table, relationship) -> Edge:
    field_eid = field_id_from_doctype(doctype_id, field)
    resolved = field_eid in table.entities
    verb = "read" if relationship == "READS_FIELD" else "write"
    return Edge(
        source_id=source,
        relationship=relationship,
        target_id=field_eid if resolved else None,
        target_hint=field_eid,
        confidence=0.9 if resolved else 0.3,
        resolver=f"frappe-field-{verb}" if resolved else f"frappe-field-{verb}-unconfirmed",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"field": field, "doctype": doctype_id},
    )


def _hook_edges(repo: Repository, table: SymbolTable, by_name: dict[str, str]) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("frappe_hook"):
        hook = obs.data.get("hook")
        handler = table.resolve_absolute(obs.data.get("handler") or "")
        doctype = by_name.get(obs.data.get("doctype") or "")
        if hook == "doc_event":
            edges.append(_hook_edge(obs, "INVOKES", doctype, handler, "frappe-doc-event"))
        elif hook == "scheduler":
            edges.append(_hook_edge(obs, "INVOKES", obs.subject, handler, "frappe-scheduler"))
        elif hook == "override_class":
            edges.append(_hook_edge(obs, "HAS_CONTROLLER", doctype, handler, "frappe-override-class"))
        elif hook == "extend_class":
            edges.append(_hook_edge(obs, "EXTENDS_CONTROLLER", doctype, handler, "frappe-extend-class"))
        elif hook == "permission":
            edges.append(_hook_edge(obs, "PERMISSION_CHECK", doctype, handler, "frappe-permission"))
        elif hook == "override_method":
            original = table.resolve_absolute(obs.data.get("original") or "")
            edges.append(_override_method_edge(obs, handler, original))
    return edges


def _override_method_edge(obs, override_id, original_id) -> Edge:
    resolved = override_id is not None and original_id is not None
    return Edge(
        source_id=override_id or obs.subject,
        relationship="OVERRIDES",
        target_id=original_id,
        target_hint=obs.data.get("original"),
        confidence=0.9 if resolved else 0.0,
        resolver="frappe-override-method" if resolved else "unresolved",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"override": obs.data.get("handler"), "original": obs.data.get("original")},
    )


def _hook_edge(obs, relationship, source, target, resolver) -> Edge:
    if not source:
        source = obs.subject
    resolved = target is not None
    return Edge(
        source_id=source,
        relationship=relationship,
        target_id=target,
        target_hint=obs.data.get("handler"),
        confidence=0.9 if resolved else 0.0,
        resolver=resolver if resolved else "unresolved",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={k: v for k, v in obs.data.items() if k != "handler"},
    )


def _orm_edges(repo: Repository, by_name: dict[str, str]) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("call"):
        relationship = _ORM_OPS.get(obs.data.get("dotted") or "")
        target = by_name.get(obs.data.get("first_arg") or "")
        if relationship and target:
            edges.append(_edge(obs.subject, relationship, target, obs.owner_file,
                               0.85, "frappe-orm", obs))
    return edges


def _endpoint_edges(repo: Repository) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("frappe_endpoint"):
        edges.append(_edge(obs.subject, "EXPOSES_ENDPOINT", obs.data["endpoint_id"],
                           obs.owner_file, 1.0, "frappe-endpoint", obs))
    return edges


def _enqueue_edges(repo: Repository, table: SymbolTable) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("frappe_enqueue"):
        job = obs.data["job_id"]
        edges.append(_edge(obs.subject, "ENQUEUES", job, obs.owner_file,
                           0.9, "frappe-enqueue", obs))
        target = table.resolve_absolute(obs.data["target"])
        if target:
            edges.append(_edge(job, "INVOKES", target, obs.owner_file,
                               0.8, "frappe-job-target", obs))
    return edges


def _doctype_by_name(table: SymbolTable) -> dict[str, str]:
    out: dict[str, str] = {}
    for entity in table.entities.values():
        if entity.kind == "doctype":
            out.setdefault(entity.name, entity.id)
    return out


def _has_field_edges(table: SymbolTable) -> list[Edge]:
    edges: list[Edge] = []
    for entity in table.entities.values():
        if entity.kind != "doctype_field":
            continue
        parent = entity.extra.get("doctype_id")
        if parent:
            edges.append(_edge(parent, "HAS_FIELD", entity.id, entity.owner_file,
                               1.0, "frappe-schema", entity))
    return edges


def _field_target_edges(repo: Repository, by_name: dict[str, str]) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("doctype_field"):
        options = obs.data.get("options")
        if obs.data.get("is_link"):
            edges.append(_link_edge(obs, "LINKS_TO", obs.data["field_id"], options, by_name))
        elif obs.data.get("is_table"):
            edges.append(_link_edge(obs, "CONTAINS_CHILD", obs.subject, options, by_name))
        elif obs.data.get("is_dynamic"):
            edges.append(_dynamic_edge(obs))
    return edges


def _link_edge(obs, relationship, source_id, options, by_name) -> Edge:
    target = by_name.get(options) if options else None
    resolved = target is not None
    return Edge(
        source_id=source_id,
        relationship=relationship,
        target_id=target,
        target_hint=options,
        confidence=1.0 if resolved else 0.0,
        resolver="frappe-link" if resolved else "unresolved",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"options": options},
    )


def _dynamic_edge(obs) -> Edge:
    return Edge(
        source_id=obs.data["field_id"],
        relationship="LINKS_TO",
        target_id=None,
        target_hint=obs.data.get("options") or "<dynamic>",
        confidence=0.0,
        resolver="frappe-dynamic-link",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"note": "Dynamic Link target is data-driven", "options": obs.data.get("options")},
    )


def _controller_and_test_edges(
    repo: Repository, by_name: dict[str, str]
) -> tuple[list[Edge], dict[str, str]]:
    edges: list[Edge] = []
    class_to_doctype: dict[str, str] = {}
    for obs in repo.observations_of_kind("frappe_controller"):
        dt_id = obs.subject
        controller = _pick_class(repo, obs.data["controller_relpath"],
                                 obs.data["class_name"], ("class",))
        if controller:
            class_to_doctype[controller.id] = dt_id
            edges.append(_edge(dt_id, "HAS_CONTROLLER", controller.id,
                               controller.owner_file, 0.95, "frappe-controller", controller))
        test = _pick_class(repo, obs.data["test_relpath"],
                           "Test" + obs.data["class_name"], ("test_class",))
        if test:
            edges.append(_edge(test.id, "TESTS", dt_id, test.owner_file,
                               0.9, "frappe-test", test))
    return edges, class_to_doctype


def _pick_class(
    repo: Repository, relpath: str, expected_name: str, kinds: tuple[str, ...]
) -> Optional[Entity]:
    candidates = repo.entities_in_file(relpath, kinds)
    if not candidates:
        return None
    for entity in candidates:
        if entity.name == expected_name:
            return entity
    return candidates[0] if len(candidates) == 1 else None


def _edge(source, relationship, target, owner_file, confidence, resolver, ref) -> Edge:
    return Edge(
        source_id=source,
        relationship=relationship,
        target_id=target,
        confidence=confidence,
        resolver=resolver,
        resolver_version=RESOLVER_VERSION,
        owner_file=owner_file,
        source_range=ref.source_range,
        evidence={"resolver": resolver},
    )
