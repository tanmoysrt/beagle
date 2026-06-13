"""Lifecycle service: ties operation edges, policy, and dispatch together.

Answers three things (design/08, 09):
- ``event_handlers(doctype, event)`` — categorised handlers for one event;
- ``lifecycle(doctype, event?)`` — ordered standard events per operation;
- ``trace(function, depth)`` — from a function, follow operations → events →
  handlers → their operations, with cycle and depth limits.

Distinguishes explicit calls, framework lifecycle dispatch, and possible
runtime-configured dispatch. Nothing is invented; uncertainty is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from beagle.lifecycle.dispatch import Dispatch, EventDispatcher, doctype_name
from beagle.lifecycle.policy import FrappeLifecyclePolicy, LifecycleEvent
from beagle.search.graph import GraphService

# Operation relationships emitted by resolution/operations.py.
OPERATION_RELS = (
    "INSERTS_DOCTYPE", "SAVES_DOCTYPE", "SUBMITS_DOCTYPE", "CANCELS_DOCTYPE",
    "UPDATES_AFTER_SUBMIT", "DB_SETS_DOCTYPE", "DELETES_DOCTYPE", "DISCARDS_DOCTYPE",
)
_STANDARD_OPS = ("INSERTS_DOCTYPE", "SAVES_DOCTYPE", "SUBMITS_DOCTYPE",
                 "CANCELS_DOCTYPE", "DELETES_DOCTYPE")
_TRACE_NODE_CAP = 50


@dataclass
class EventExpansion:
    event: LifecycleEvent
    dispatch: Optional[Dispatch]


@dataclass
class OperationExpansion:
    relationship: str
    doctype_id: str
    events: list[EventExpansion] = field(default_factory=list)
    override_note: str = ""


@dataclass
class LifecycleReport:
    doctype_id: str
    operations: list[OperationExpansion] = field(default_factory=list)
    policy: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class TraceGraph:
    root: str
    nodes: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (label, kind)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (src, dst, category)
    notes: list[str] = field(default_factory=list)
    truncated: bool = False


class LifecycleService:
    def __init__(self, repo, graph: GraphService, policy=None, dispatcher=None):
        self.repo = repo
        self.graph = graph
        self.policy = policy or FrappeLifecyclePolicy()
        self.dispatcher = dispatcher or EventDispatcher(repo, graph)

    # --- resolution helpers -------------------------------------------

    def resolve_doctype(self, ref: str) -> Optional[str]:
        if ref.startswith("doctype://"):
            return ref
        for entity in self.graph.resolve(ref):
            if entity.kind == "doctype":
                return entity.id
        return None

    # --- event handlers -----------------------------------------------

    def event_handlers(self, doctype_ref: str, event: str) -> Optional[Dispatch]:
        doctype_id = self.resolve_doctype(doctype_ref)
        if doctype_id is None:
            return None
        return self.dispatcher.handlers_for(doctype_id, event)

    # --- lifecycle ----------------------------------------------------

    def lifecycle(self, doctype_ref: str, event: Optional[str] = None) -> Optional[LifecycleReport]:
        doctype_id = self.resolve_doctype(doctype_ref)
        if doctype_id is None:
            return None
        report = LifecycleReport(doctype_id=doctype_id, policy=self.policy.meta)
        relationships = self._ops_for_event(event) if event else _STANDARD_OPS
        for rel in relationships:
            report.operations.append(self._expand_operation(doctype_id, rel, event))
        report.notes.append("event order is the standard Document policy; effective "
                             "controller overrides may alter it")
        return report

    def _ops_for_event(self, event: str) -> list[str]:
        return [rel for rel in OPERATION_RELS
                if any(e.name == event for e in self.policy.events_for(rel))]

    def _expand_operation(self, doctype_id: str, rel: str, only_event: Optional[str]) -> OperationExpansion:
        op = OperationExpansion(relationship=rel, doctype_id=doctype_id)
        for event in self.policy.events_for(rel):
            if only_event and event.name != only_event:
                continue
            dispatch = None
            if event.name in self.policy.dispatch_events:
                dispatch = self.dispatcher.handlers_for(doctype_id, event.name)
            op.events.append(EventExpansion(event=event, dispatch=dispatch))
        op.override_note = self._override_note(doctype_id, rel)
        return op

    def _override_note(self, doctype_id: str, rel: str) -> str:
        method = {"INSERTS_DOCTYPE": "insert", "SAVES_DOCTYPE": "save",
                  "SUBMITS_DOCTYPE": "submit", "CANCELS_DOCTYPE": "cancel"}.get(rel)
        if not method:
            return ""
        for controller in self.repo.edges_from(doctype_id, ("HAS_CONTROLLER",)):
            if controller.target_id and self.repo.get_entity(f"{controller.target_id}.{method}"):
                return f"controller overrides {method}(); standard lifecycle is conditional"
        return ""

    # --- trace --------------------------------------------------------

    def trace(self, entity_ref: str, depth: int = 2) -> Optional[TraceGraph]:
        start = self._resolve_function(entity_ref)
        if start is None:
            return None
        graph = TraceGraph(root=start)
        self._add_node(graph, start, self._label(start), "function")
        self._expand_function(graph, start, depth, set())
        return graph

    def _resolve_function(self, ref: str) -> Optional[str]:
        for entity in self.graph.resolve(ref):
            if entity.kind in ("function", "method", "test_function"):
                return entity.id
        return None

    def _expand_function(self, graph: TraceGraph, fn_id: str, depth: int, seen: set) -> None:
        if fn_id in seen or len(graph.nodes) >= _TRACE_NODE_CAP:
            graph.truncated = graph.truncated or len(graph.nodes) >= _TRACE_NODE_CAP
            return
        seen.add(fn_id)
        for edge in self.repo.edges_from(fn_id, (*OPERATION_RELS, "RUNS_EVENT")):
            if edge.target_id:
                self._expand_operation_trace(graph, fn_id, edge, depth, seen)

    def _expand_operation_trace(self, graph, fn_id, edge, depth, seen) -> None:
        doctype = edge.target_id
        self._add_node(graph, doctype, doctype_name(doctype), "doctype")
        graph.edges.append((fn_id, doctype, "operation"))
        for event_name in self._events_for_edge(edge):
            self._expand_event(graph, doctype, event_name, depth, seen)

    def _events_for_edge(self, edge) -> list[str]:
        if edge.relationship == "RUNS_EVENT":
            return [edge.evidence.get("event")] if edge.evidence.get("event") else []
        return [e.name for e in self.policy.events_for(edge.relationship)
                if e.name in self.policy.dispatch_events]

    def _expand_event(self, graph, doctype_id, event_name, depth, seen) -> None:
        event_node = f"frappe-event://{doctype_name(doctype_id)}/{event_name}"
        if event_node in seen:  # framework cycle guard
            return
        seen.add(event_node)
        self._add_node(graph, event_node, event_name, "event")
        graph.edges.append((doctype_id, event_node, "framework"))
        dispatch = self.dispatcher.handlers_for(doctype_id, event_name)
        graph.notes.extend(n for n in dispatch.notes if n not in graph.notes)
        for handler in dispatch.all_handlers():
            self._expand_handler(graph, event_node, handler, depth, seen)

    def _expand_handler(self, graph, event_node, handler, depth, seen) -> None:
        hid = handler.target_id or f"hint://{handler.hint}"
        label = self._label(handler.target_id) if handler.target_id else handler.hint
        self._add_node(graph, hid, label, handler.category)
        category = "runtime" if handler.category == "runtime" else "framework"
        graph.edges.append((event_node, hid, category))
        if handler.target_id and depth > 0:
            self._expand_function(graph, handler.target_id, depth - 1, seen)

    # --- helpers ------------------------------------------------------

    def _add_node(self, graph: TraceGraph, node_id: str, label: str, kind: str) -> None:
        graph.nodes.setdefault(node_id, (label, kind))

    def _label(self, entity_id: Optional[str]) -> str:
        if not entity_id:
            return "?"
        entity = self.repo.get_entity(entity_id)
        return entity.qualified_name if entity else entity_id
