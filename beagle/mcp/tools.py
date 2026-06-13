"""Application services behind the MCP server, as plain dict-returning methods.

This is the testable core: every method delegates to the same GraphService /
SearchEngine / ContextCompiler the CLI uses, then serializes to compact,
JSON-friendly dicts that carry stable entity ids for follow-up calls. The MCP
transport layer (server.py) only wires these to tool decorators — no extra
logic, per design/04 stage 8.
"""

from __future__ import annotations

from typing import Optional

from beagle.context import ContextCompiler
from beagle.explain import Explainer
from beagle.investigate import Investigator
from beagle.models import Edge, Entity
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

_CALL_LIMIT = 50


class BeagleTools:
    def __init__(self, workspace: Workspace):
        self.ws = workspace
        self.graph = GraphService(workspace.repo)
        self.search_engine = SearchEngine(workspace.db)

    # --- status / search ----------------------------------------------

    def index_status(self) -> dict:
        run = self.ws.repo.latest_run()
        return {
            "root": str(self.ws.root),
            "counts": self.ws.repo.counts(),
            "last_run": dict(run) if run else None,
        }

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return [
            {
                "entity_id": r.entity_id,
                "file": r.owner_file,
                "start_line": r.source_range.start_line,
                "end_line": r.source_range.end_line,
                "snippet": r.snippet,
            }
            for r in self.search_engine.search(query, limit=limit)
        ]

    # --- lookup --------------------------------------------------------

    def resolve(self, name: str, limit: int = 25) -> list[dict]:
        return [_entity_dict(e) for e in self.graph.resolve(name, limit=limit)]

    def show(self, entity_id: str) -> dict:
        resolved = self._one(entity_id)
        if isinstance(resolved, dict):
            return resolved
        return _entity_dict(self.ws.repo.get_entity(resolved), full=True)

    def relations(self, entity_id: str) -> dict:
        resolved = self._one(entity_id)
        if isinstance(resolved, dict):
            return resolved
        rel = self.graph.relations(resolved)
        return {
            "entity": _entity_dict(rel.entity),
            "outgoing": [self._edge_dict(e, "target_id") for e in rel.outgoing],
            "incoming": [self._edge_dict(e, "source_id") for e in rel.incoming],
        }

    def callers(self, entity_id: str) -> dict:
        return self._edge_side(entity_id, "callers")

    def callees(self, entity_id: str) -> dict:
        return self._edge_side(entity_id, "callees")

    def find_path(self, source: str, target: str) -> dict:
        src, dst = self._one(source), self._one(target)
        if isinstance(src, dict):
            return src
        if isinstance(dst, dict):
            return dst
        trail = self.graph.path(src, dst)
        return {"path": [_entity_dict(self.ws.repo.get_entity(i)) for i in (trail or [])]}

    def impact(self, entity_id: str, depth: int = 3) -> dict:
        resolved = self._one(entity_id)
        if isinstance(resolved, dict):
            return resolved
        nodes = self.graph.impact(resolved, max_depth=depth)
        return {"impact": [
            {"entity": _entity_dict(self.ws.repo.get_entity(n.entity_id)),
             "distance": n.distance, "via": n.via}
            for n in nodes if self.ws.repo.get_entity(n.entity_id)
        ]}

    def uses_doctype(self, name: str) -> dict:
        resolved = self._one(name)
        if isinstance(resolved, dict):
            return resolved
        return {"uses": [self._edge_dict(e, "source_id") for e in self.graph.uses_doctype(resolved)]}

    def tests(self, entity_id: str) -> dict:
        resolved = self._one(entity_id)
        if isinstance(resolved, dict):
            return resolved
        return {"tests": [self._edge_dict(e, "source_id") for e in self.graph.tests(resolved)]}

    def reads_field(self, field: str) -> dict:
        return self._field_access(field, ("READS_DOCTYPE",))

    def writes_field(self, field: str) -> dict:
        return self._field_access(field, ("WRITES_DOCTYPE", "CREATES_DOCTYPE"))

    # --- context / source ---------------------------------------------

    def context(self, query: str, intent: str = "understand", max_tokens: int = 6000) -> dict:
        compiler = ContextCompiler(self.ws.repo, self.graph, self.search_engine, self.ws.read_range)
        bundle = compiler.compile(intent, query, max_tokens=max_tokens)
        return {
            "intent": bundle.intent,
            "used_tokens": bundle.used_tokens,
            "max_tokens": bundle.max_tokens,
            "notes": bundle.notes,
            "items": [
                {
                    "entity_id": i.entity_id, "kind": i.kind,
                    "qualified_name": i.qualified_name, "path": i.path,
                    "start_line": i.start_line, "end_line": i.end_line,
                    "reason": i.reason, "confidence": i.confidence, "excerpt": i.excerpt,
                }
                for i in bundle.items
            ],
        }

    def investigate(self, query: str, max_tokens: int = 6000) -> dict:
        inv = Investigator(self.ws.repo, self.graph, self.search_engine, self.ws.read_range)
        report = inv.investigate(query, max_tokens=max_tokens)
        return {
            "notes": report.notes,
            "sections": [{"title": s.title, "lines": s.lines} for s in report.sections],
            "cited": [
                {"entity_id": e, "path": p, "start_line": s, "end_line": en}
                for e, p, s, en in report.cited
            ],
        }

    def explain_function(self, entity: str, include_mermaid: bool = False,
                         expand_calls: int = 0) -> dict:
        explainer = Explainer(self.ws.repo, self.graph, self.ws.read_range)
        result = explainer.explain(entity, include_mermaid=include_mermaid, expand_calls=expand_calls)
        if result.entity is None:
            return {"candidates": result.candidates}
        return {
            "entity_id": result.entity.id,
            "summary": result.summary,
            "mermaid": result.mermaid,
            "node_sources": [
                {"node": nid, "path": path, "line": line}
                for nid, path, line in result.node_sources
            ],
        }

    def read_source(self, entity_id: str) -> dict:
        entity = self.ws.repo.get_entity(entity_id)
        if entity is None:
            return {"error": f"unknown entity: {entity_id}"}
        text = self.ws.read_range(
            entity.owner_file, entity.source_range.start_line, entity.source_range.end_line
        )
        return {
            "entity_id": entity_id, "path": entity.owner_file,
            "start_line": entity.source_range.start_line,
            "end_line": entity.source_range.end_line, "source": text,
        }

    # --- helpers -------------------------------------------------------

    def _one(self, ref: str):
        """Resolve to a single entity id, or a dict of candidates if ambiguous."""
        matches = self.graph.resolve(ref)
        if not matches:
            return {"error": f"no entity matches: {ref}"}
        if len(matches) > 1 and matches[0].id != ref:
            return {"candidates": [_entity_dict(m) for m in matches[:15]]}
        return matches[0].id

    def _edge_side(self, ref: str, side: str) -> dict:
        resolved = self._one(ref)
        if isinstance(resolved, dict):
            return resolved
        edges = self.graph.callers(resolved) if side == "callers" else self.graph.callees(resolved)
        which = "source_id" if side == "callers" else "target_id"
        return {side: [self._edge_dict(e, which) for e in edges[:_CALL_LIMIT]]}

    def _field_access(self, ref: str, relationships: tuple[str, ...]) -> dict:
        field = self._resolve_field(ref)
        if field is None:
            return {"error": f"no field matches: {ref}"}
        doctype_id = field.extra.get("doctype_id")
        edges = self.ws.repo.edges_to(doctype_id, relationships)
        return {
            "field": field.id,
            "doctype": doctype_id,
            "note": "field-level access not tracked yet; results are DocType-granular",
            "access": [self._edge_dict(e, "source_id") for e in edges],
        }

    def _resolve_field(self, ref: str) -> Optional[Entity]:
        if ref.startswith("doctype-field://"):
            return self.ws.repo.get_entity(ref)
        for entity in self.ws.repo.find_entities_by_name(ref):
            if entity.kind == "doctype_field":
                return entity
        return None

    def _edge_dict(self, edge: Edge, other: str) -> dict:
        other_id = edge.target_id if other == "target_id" else edge.source_id
        entity = self.ws.repo.get_entity(other_id) if other_id else None
        return {
            "relationship": edge.relationship,
            "entity_id": other_id,
            "qualified_name": entity.qualified_name if entity else None,
            "target_hint": edge.target_hint,
            "confidence": edge.confidence,
            "resolver": edge.resolver,
            "file": edge.owner_file,
            "start_line": edge.source_range.start_line,
        }


def _entity_dict(entity: Optional[Entity], full: bool = False) -> Optional[dict]:
    if entity is None:
        return None
    data = {
        "entity_id": entity.id,
        "kind": entity.kind,
        "qualified_name": entity.qualified_name,
        "file": entity.owner_file,
        "start_line": entity.source_range.start_line,
        "end_line": entity.source_range.end_line,
    }
    if full:
        data["signature"] = entity.signature
        data["docstring"] = entity.docstring
        data["extra"] = entity.extra
    return data
