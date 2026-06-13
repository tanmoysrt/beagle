"""Resolve what actually runs for a (DocType, event) — design/09.

Differentiates dispatch categories rather than flattening into one CALLS list:
effective controller method (via override/extend MRO), exact-DocType
``doc_events``, wildcard ``doc_events["*"]``, and runtime-configured channels
(Notification/Webhook/Server Script) which are reported as existing-but-unknown
without a site snapshot. Resolves hooks without importing or executing
``hooks.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_CONTROLLER = "controller"
_EXACT = "exact_doc_event"
_WILDCARD = "wildcard_doc_event"
_RUNTIME = "runtime"

# Events after which Frappe may invoke runtime-configured integrations.
_RUNTIME_EVENTS = {
    "after_insert", "on_update", "on_submit", "on_cancel", "on_change",
    "on_update_after_submit", "on_trash", "after_delete",
}
_RUNTIME_CHANNELS = ("Notification", "Webhook", "Server Script")


@dataclass
class Handler:
    category: str
    target_id: Optional[str]
    hint: str
    confidence: float
    app: Optional[str] = None
    source_file: Optional[str] = None


@dataclass
class Dispatch:
    doctype_id: str
    event: str
    controller: Optional[Handler] = None
    exact: list[Handler] = field(default_factory=list)
    wildcard: list[Handler] = field(default_factory=list)
    runtime: list[Handler] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def all_handlers(self) -> list[Handler]:
        out = [self.controller] if self.controller else []
        return out + self.exact + self.wildcard + self.runtime


def doctype_name(doctype_id: str) -> str:
    return doctype_id.rsplit("/", 1)[-1] if "/" in doctype_id else doctype_id


def resolve_dotted_path(repo, dotted: str) -> Optional[str]:
    """Map a fully-qualified dotted handler path to an entity id, if indexed."""
    parts = dotted.split(".")
    for tail in (1, 2):
        if len(parts) > tail:
            cand = f"python://{'.'.join(parts[:-tail])}#{'.'.join(parts[-tail:])}"
            if repo.get_entity(cand) is not None:
                return cand
    return None


class EventDispatcher:
    def __init__(self, repo, graph):
        self.repo = repo
        self.graph = graph
        self._hooks = repo.observations_of_kind("frappe_hook")

    def handlers_for(self, doctype_id: str, event: str) -> Dispatch:
        dispatch = Dispatch(doctype_id=doctype_id, event=event)
        name = doctype_name(doctype_id)
        dispatch.controller = self._controller(doctype_id, event)
        dispatch.exact = self._doc_events(name, event, _EXACT)
        dispatch.wildcard = self._doc_events("*", event, _WILDCARD)
        dispatch.runtime = self._runtime(event)
        self._note_ordering(dispatch)
        return dispatch

    # --- controller MRO -----------------------------------------------

    def _controller(self, doctype_id: str, event: str) -> Optional[Handler]:
        controllers = [e.target_id for e in self.repo.edges_from(doctype_id, ("HAS_CONTROLLER",)) if e.target_id]
        mixins = [e.target_id for e in self.repo.edges_from(doctype_id, ("EXTENDS_CONTROLLER",)) if e.target_id]
        uncertain = len(controllers) > 1  # multiple overrides, app order unknown
        for cls in [*mixins, *controllers]:
            method = self._find_method(cls, event, set())
            if method:
                entity = self.repo.get_entity(method)
                return Handler(_CONTROLLER, method, method,
                               0.90 if uncertain else 0.99,
                               source_file=entity.owner_file if entity else None)
        return None

    def _mro_classes(self, doctype_id: str) -> list[str]:
        """Effective controller MRO: extend mixins first, then override/base
        controllers, then their INHERITS bases (depth-first, deduped). This is
        the Frappe-injected order a pure-Python base walk cannot see."""
        roots = [e.target_id for e in self.repo.edges_from(doctype_id, ("EXTENDS_CONTROLLER",)) if e.target_id]
        roots += [e.target_id for e in self.repo.edges_from(doctype_id, ("HAS_CONTROLLER",)) if e.target_id]
        order: list[str] = []
        seen: set = set()

        def walk(cls: str) -> None:
            if cls in seen:
                return
            seen.add(cls)
            order.append(cls)
            for edge in self.repo.edges_from(cls, ("INHERITS",)):
                if edge.target_id:
                    walk(edge.target_id)

        for root in roots:
            walk(root)
        return order

    def controller_chain(self, doctype_id: str, event: str) -> list[str]:
        """Ordered method ids that define ``event`` along the controller MRO.
        chain[0] is the effective controller; later entries run only when an
        earlier one calls ``super().<event>()`` (super-continuation, design/09)."""
        chain = []
        for cls in self._mro_classes(doctype_id):
            method = f"{cls}.{event}"
            if self.repo.get_entity(method) is not None:
                chain.append(method)
        return chain

    def _find_method(self, class_id: str, name: str, seen: set) -> Optional[str]:
        if class_id in seen:
            return None
        seen.add(class_id)
        candidate = f"{class_id}.{name}"
        if self.repo.get_entity(candidate) is not None:
            return candidate
        for edge in self.repo.edges_from(class_id, ("INHERITS",)):
            if edge.target_id:
                found = self._find_method(edge.target_id, name, seen)
                if found:
                    return found
        return None

    # --- doc_events ----------------------------------------------------

    def _doc_events(self, doctype: str, event: str, category: str) -> list[Handler]:
        handlers: list[Handler] = []
        for obs in self._hooks:
            data = obs.data
            if data.get("hook") != "doc_event" or data.get("doctype") != doctype:
                continue
            if data.get("event") != event:
                continue
            dotted = data.get("handler") or ""
            handlers.append(Handler(
                category=category,
                target_id=resolve_dotted_path(self.repo, dotted),
                hint=dotted,
                confidence=0.98,
                app=obs.owner_file.split("/", 1)[0],
                source_file=obs.owner_file,
            ))
        return handlers

    # --- runtime -------------------------------------------------------

    def _runtime(self, event: str) -> list[Handler]:
        if event not in _RUNTIME_EVENTS:
            return []
        return [Handler(_RUNTIME, None, channel, 0.70) for channel in _RUNTIME_CHANNELS]

    def _note_ordering(self, dispatch: Dispatch) -> None:
        apps = {h.app for h in dispatch.exact + dispatch.wildcard if h.app}
        if len(apps) > 1:
            dispatch.notes.append(
                "multiple apps declare handlers; installed-app order unknown — "
                "exact execution order not determined"
            )
        if dispatch.runtime:
            dispatch.notes.append(
                "runtime dispatch channels exist; concrete handlers unknown without a site snapshot"
            )
