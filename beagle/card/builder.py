"""Build a Function Context Card from indexed evidence (design/12).

Reuses the existing graph: resolved edges (calls, fields, doctype ops,
endpoints, hooks, jobs, tests), raw observations (raise/except/comparison/
assignment/call), and the lifecycle service for implicit Frappe behaviour. It
derives structured facts only — direct and indirect behaviour are kept apart,
and weak responsibility inference is reported as such rather than guessed.

Keeps parsing/resolution out: this is a retrieval-and-assembly layer over facts
that already exist in the index.
"""

from __future__ import annotations

from typing import Optional

from beagle.card.classify import action_verb, call_category, external_boundary
from beagle.card.model import (Effect, Entrypoint, ExternalBoundary, FailurePath,
                               FunctionContext, Guard, Identity, ImportantCall,
                               LifecyclePath, RelatedEntity, Responsibility)
from beagle.models import Entity, Observation
from beagle.search.graph import GraphService

_FUNCTION_KINDS = ("function", "method", "test_function")
_SIGNAL_KINDS = ("call", "raise", "except", "comparison", "counter", "assignment")
_OPERATIONS = {
    "SAVES_DOCTYPE": "saves", "INSERTS_DOCTYPE": "inserts",
    "SUBMITS_DOCTYPE": "submits", "CANCELS_DOCTYPE": "cancels",
    "DB_SETS_DOCTYPE": "db_set", "DELETES_DOCTYPE": "deletes",
    "DISCARDS_DOCTYPE": "discards",
}
_CALL_CAP = 8


class ContextCardBuilder:
    def __init__(self, repo, graph: GraphService, reader, lifecycle=None):
        self.repo = repo
        self.graph = graph
        self.reader = reader
        self.lifecycle = lifecycle

    def build(self, ref: str) -> Optional[FunctionContext]:
        entity = self._resolve(ref)
        if entity is None:
            matches = self.graph.resolve(ref)
            if not matches:
                return None
            return FunctionContext(
                identity=_unknown_identity(ref), responsibility=Responsibility("", "", ""),
                candidates=[m.id for m in matches[:15]],
            )
        obs = self.repo.observations_for_subjects([entity.id], _SIGNAL_KINDS)
        return self._assemble(entity, obs)

    def _resolve(self, ref: str) -> Optional[Entity]:
        matches = self.graph.resolve(ref)
        functions = [m for m in matches if m.kind in _FUNCTION_KINDS]
        if len(functions) == 1:
            return functions[0]
        if len(matches) == 1 and matches[0].kind in _FUNCTION_KINDS:
            return matches[0]
        return None

    def _assemble(self, entity: Entity, obs: list[Observation]) -> FunctionContext:
        reads, writes = self._reads(entity.id), self._writes(entity.id, obs)
        calls = self._important_calls(obs)
        lifecycle = self._lifecycle(entity.id)
        card = FunctionContext(
            identity=self._identity(entity),
            responsibility=Responsibility("", "", ""),
            entrypoints=self._entrypoints(entity.id),
            guards=self._guards(entity, obs),
            reads=reads, writes=writes, calls=calls, lifecycle=lifecycle,
            jobs=self._jobs(entity.id),
            external_boundaries=self._external(obs),
            failures=self._failures(obs),
            callers=self._callers(entity.id),
            tests=self._tests(entity.id),
        )
        card.unknowns = self._unknowns(entity, card, obs)
        card.responsibility = self._responsibility(entity, card)
        return card

    # --- identity ------------------------------------------------------

    def _identity(self, e: Entity) -> Identity:
        return Identity(
            entity_id=e.id, qualified_name=e.qualified_name, kind=e.kind,
            path=e.owner_file, start_line=e.source_range.start_line,
            end_line=e.source_range.end_line, signature=e.signature,
            decorators=list(e.extra.get("decorators", [])), docstring=e.docstring,
        )

    # --- entrypoints ---------------------------------------------------

    _ENTRY_RESOLVERS = {"frappe-doc-event": "doc_event", "frappe-scheduler": "scheduler",
                        "frappe-job-target": "job"}

    def _entrypoints(self, eid: str) -> list[Entrypoint]:
        out: list[Entrypoint] = []
        if self.repo.edges_from(eid, ("EXPOSES_ENDPOINT",)):
            out.append(Entrypoint("endpoint", "whitelisted method"))
        for edge in self.repo.edges_to(eid, ("INVOKES", "ENQUEUES")):
            kind = self._ENTRY_RESOLVERS.get(edge.resolver, "invoked")
            detail = edge.evidence.get("event") or edge.evidence.get("frequency") or edge.resolver
            out.append(Entrypoint(kind, str(detail), edge.source_id))
        if self._is_lifecycle_method(eid):
            out.append(Entrypoint("controller-lifecycle", eid.rsplit(".", 1)[-1]))
        return out

    def _is_lifecycle_method(self, eid: str) -> bool:
        method = eid.rsplit(".", 1)[-1] if "." in eid else ""
        return method in self.lifecycle.policy.dispatch_events if self.lifecycle else False

    # --- guards --------------------------------------------------------

    def _guards(self, entity: Entity, obs: list[Observation]) -> list[Guard]:
        guards: list[Guard] = []
        for dec in entity.extra.get("decorators", []):
            if "whitelist" in dec or "only_for" in dec or "permission" in dec:
                guards.append(Guard("decorator", dec, entity.source_range.start_line))
        for o in obs:
            if o.kind == "comparison":
                guards.append(Guard("threshold",
                                    f"{o.data.get('left_code')} {o.data.get('op')} {o.data.get('value')}",
                                    o.source_range.start_line))
            elif o.kind == "call" and o.data.get("dotted") == "frappe.throw":
                guards.append(Guard("throw", o.data.get("first_arg") or "frappe.throw",
                                    o.source_range.start_line))
        return guards

    # --- reads / writes ------------------------------------------------

    def _reads(self, eid: str) -> list[Effect]:
        out = [Effect("field-read", self._field_name(e.target_id), e.source_range.start_line,
                      _certainty(e)) for e in self.repo.edges_from(eid, ("READS_FIELD",))]
        out += [Effect("doctype-read", self._doctype_name(e.target_id), e.source_range.start_line)
                for e in self.repo.edges_from(eid, ("READS_DOCTYPE",)) if e.target_id]
        return out

    def _writes(self, eid: str, obs: list[Observation]) -> list[Effect]:
        out = [Effect("field-write", self._field_name(e.target_id), e.source_range.start_line,
                      _certainty(e)) for e in self.repo.edges_from(eid, ("WRITES_FIELD",))]
        for o in obs:
            if o.kind == "assignment" and _is_status_target(o.data.get("target_code")):
                out.append(Effect("status-write", o.data["target_code"], o.source_range.start_line))
        for rel, verb in _OPERATIONS.items():
            for e in self.repo.edges_from(eid, (rel,)):
                if e.target_id:
                    out.append(Effect(verb, self._doctype_name(e.target_id), e.source_range.start_line))
        return out

    # --- calls / jobs / external --------------------------------------

    def _important_calls(self, obs: list[Observation]) -> list[ImportantCall]:
        out: list[ImportantCall] = []
        seen = set()
        for o in obs:
            if o.kind != "call":
                continue
            category = call_category(o.data)
            name = o.data.get("func_code") or o.data.get("dotted") or "?"
            if category is None or name in seen:
                continue
            seen.add(name)
            out.append(ImportantCall(name, category, bool(o.data.get("dotted")),
                                     o.source_range.start_line))
        return out[:_CALL_CAP]

    def _jobs(self, eid: str) -> list[Effect]:
        return [Effect("enqueue", e.target_hint or self._short(e.target_id),
                       e.source_range.start_line, _certainty(e))
                for e in self.repo.edges_from(eid, ("ENQUEUES",))]

    def _external(self, obs: list[Observation]) -> list[ExternalBoundary]:
        out: list[ExternalBoundary] = []
        for o in obs:
            if o.kind != "call":
                continue
            boundary = external_boundary(o.data)
            if boundary:
                out.append(ExternalBoundary(boundary[0], boundary[1], o.source_range.start_line))
        return out

    # --- lifecycle -----------------------------------------------------

    def _lifecycle(self, eid: str) -> list[LifecyclePath]:
        if self.lifecycle is None:
            return []
        out, seen = [], set()
        for rel, verb in _OPERATIONS.items():
            for e in self.repo.edges_from(eid, (rel,)):
                if e.target_id and (rel, e.target_id) not in seen:
                    seen.add((rel, e.target_id))
                    out.append(self._lifecycle_path(rel, verb, e.target_id))
        return out

    def _lifecycle_path(self, rel: str, verb: str, doctype_id: str) -> LifecyclePath:
        events = [ev.name for ev in self.lifecycle.policy.events_for(rel)]
        return LifecyclePath(verb, self._doctype_name(doctype_id), events,
                             self._handlers(doctype_id, events))

    def _handlers(self, doctype_id: str, events: list[str]) -> list[str]:
        targets: list[str] = []
        for name in events:
            if name not in self.lifecycle.policy.dispatch_events:
                continue
            dispatch = self.lifecycle.event_handlers(doctype_id, name)
            if dispatch is None:
                continue
            if dispatch.controller and dispatch.controller.target_id:
                targets.append(self._short(dispatch.controller.target_id))
            targets += [self._short(h.target_id) for h in (*dispatch.exact, *dispatch.wildcard)
                        if h.target_id]
        return list(dict.fromkeys(targets))

    # --- failures / callers / tests -----------------------------------

    def _failures(self, obs: list[Observation]) -> list[FailurePath]:
        out: list[FailurePath] = []
        for o in obs:
            if o.kind == "raise" and o.data.get("exc"):
                out.append(FailurePath("raises", o.data["exc"], o.source_range.start_line))
            elif o.kind == "except" and o.data.get("types"):
                out.append(FailurePath("handles", ", ".join(o.data["types"]), o.source_range.start_line))
            elif o.kind == "call" and o.data.get("dotted") == "frappe.throw":
                out.append(FailurePath("throws", o.data.get("first_arg") or "frappe.throw",
                                       o.source_range.start_line))
        return out

    def _callers(self, eid: str) -> list[RelatedEntity]:
        out, seen = [], set()
        for edge in self.repo.edges_to(eid, ("CALLS", "INVOKES", "ENQUEUES")):
            source = self.repo.get_entity(edge.source_id)
            if source is None or source.id in seen or source.kind == "test_function":
                continue
            seen.add(source.id)
            out.append(RelatedEntity(source.id, source.qualified_name, source.kind))
        return out[:_CALL_CAP]

    def _tests(self, eid: str) -> list[RelatedEntity]:
        out, seen = [], set()
        for edge in self.graph.tests(eid):
            test = self.repo.get_entity(edge.source_id)
            if test and test.id not in seen:
                seen.add(test.id)
                out.append(RelatedEntity(test.id, test.qualified_name, test.kind))
        return out

    # --- responsibility / unknowns ------------------------------------

    def _responsibility(self, entity: Entity, card: FunctionContext) -> Responsibility:
        action = action_verb(entity.name)
        subject = self._subject(entity)
        evidence = [f"method name: {entity.name}"]
        evidence += [f"writes {w.target}" for w in card.writes[:3]]
        evidence += [f"calls {c.name}" for c in card.calls if c.category == "business"][:2]
        if card.entrypoints:
            evidence.append(f"entrypoint: {card.entrypoints[0].kind}")
        confidence = self._confidence(card)
        summary = f"{action} {subject}".strip() if confidence >= 0.4 else "(responsibility uncertain)"
        return Responsibility(action, subject, summary, evidence, confidence)

    def _confidence(self, card: FunctionContext) -> float:
        score = 0.3
        if card.writes:
            score += 0.25
        if any(w.kind in ("status-write", "save", "insert") for w in card.writes):
            score += 0.15
        if card.entrypoints:
            score += 0.15
        if any(c.category == "business" for c in card.calls):
            score += 0.1
        if card.tests:
            score += 0.05
        return round(min(score, 0.98), 2)

    def _subject(self, entity: Entity) -> str:
        # Method of a controller class -> the owning DocType-ish class name.
        if entity.kind == "method" and "#" in entity.id:
            qual = entity.id.split("#", 1)[1]
            return qual.rsplit(".", 1)[0] if "." in qual else qual
        return entity.qualified_name.rsplit(".", 1)[0]

    def _unknowns(self, entity: Entity, card: FunctionContext, obs: list[Observation]) -> list[str]:
        out: list[str] = []
        unresolved = [e.target_hint or "?" for e in self.repo.edges_from(entity.id, ("CALLS",))
                      if e.target_id is None]
        if unresolved:
            out.append("unresolved calls (dynamic/external receiver): "
                       + ", ".join(dict.fromkeys(unresolved))[:120])
        if card.lifecycle:
            out.append("installed-app override order and site-configured runtime hooks "
                       "are not resolvable from the repo")
        if (card.writes or card.lifecycle) and not card.tests:
            out.append("no related tests found")
        return out

    # --- naming --------------------------------------------------------

    def _short(self, entity_id: Optional[str]) -> str:
        if not entity_id:
            return "?"
        entity = self.repo.get_entity(entity_id)
        return entity.qualified_name if entity else entity_id

    def _doctype_name(self, doctype_id: Optional[str]) -> str:
        if not doctype_id:
            return "?"
        entity = self.repo.get_entity(doctype_id)
        return entity.name if entity else doctype_id.rsplit("/", 1)[-1]

    def _field_name(self, field_id: Optional[str]) -> str:
        if not field_id:
            return "?"
        entity = self.repo.get_entity(field_id)
        if entity is None:
            return field_id.rsplit("#", 1)[-1]
        return entity.qualified_name


def _unknown_identity(ref: str) -> Identity:
    return Identity(entity_id=ref, qualified_name=ref, kind="", path="", start_line=0, end_line=0)


def _certainty(edge) -> str:
    return "unconfirmed" if "unconfirmed" in (edge.resolver or "") else "resolved"


def _is_status_target(target: Optional[str]) -> bool:
    if not target:
        return False
    return target.endswith((".status", ".state")) or target in ("status", "state")
