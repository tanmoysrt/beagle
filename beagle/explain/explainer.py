"""Explain a function: a prose summary plus an optional Mermaid flow.

Summary draws on resolved edges and signal observations (callees, callers,
DocType reads/writes, enqueued jobs, raises/excepts). The diagram comes from the
deterministic flow builder. ``expand_calls`` inlines a few resolved callees one
level deep, within the node cap. No step or edge is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from beagle.explain.flow import FlowGraph, build_flow
from beagle.explain.mermaid import render
from beagle.models import Entity
from beagle.search.graph import GraphService

_FUNCTION_KINDS = ("function", "method", "test_function")
_SUMMARY_OBS = ("raise", "except")


@dataclass
class Explanation:
    entity: Entity
    summary: list[str] = field(default_factory=list)
    mermaid: Optional[str] = None
    node_sources: list[tuple[str, str, int]] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


class Explainer:
    def __init__(self, repo, graph: GraphService, reader):
        self.repo = repo
        self.graph = graph
        self.reader = reader

    def explain(self, ref: str, include_mermaid: bool = False, expand_calls: int = 0) -> Explanation:
        entity = self._resolve(ref)
        if entity is None:
            matches = self.graph.resolve(ref)
            return Explanation(entity=None, candidates=[m.id for m in matches[:15]])  # type: ignore[arg-type]
        explanation = Explanation(entity=entity, summary=self._summary(entity))
        if include_mermaid:
            graph = self._flow(entity, expand_calls)
            if graph:
                explanation.mermaid = render(graph)
                explanation.node_sources = [(n.id, entity.owner_file, n.line) for n in graph.nodes]
        return explanation

    def _resolve(self, ref: str) -> Optional[Entity]:
        matches = self.graph.resolve(ref)
        functions = [m for m in matches if m.kind in _FUNCTION_KINDS]
        if len(functions) == 1:
            return functions[0]
        if len(matches) == 1 and matches[0].kind in _FUNCTION_KINDS:
            return matches[0]
        return None

    # --- summary -------------------------------------------------------

    def _summary(self, entity: Entity) -> list[str]:
        lines = [f"{entity.qualified_name}  ({entity.owner_file}:"
                 f"{entity.source_range.start_line}-{entity.source_range.end_line})"]
        if entity.signature:
            lines.append(f"signature: {entity.signature}")
        if entity.docstring:
            lines.append(f"doc: {entity.docstring.splitlines()[0]}")
        lines += self._edge_summary(entity.id)
        lines += self._obs_summary(entity.id)
        return lines

    def _edge_summary(self, eid: str) -> list[str]:
        out = []
        callees = [e.target_id for e in self.graph.callees(eid) if e.target_id]
        if callees:
            out.append(f"calls: {', '.join(self._short(c) for c in callees[:8])}")
        callers = self.graph.callers(eid)
        if callers:
            out.append(f"called by {len(callers)} site(s)")
        for rel, verb in (("READS_DOCTYPE", "reads"), ("WRITES_DOCTYPE", "writes"),
                          ("CREATES_DOCTYPE", "creates"), ("ENQUEUES", "enqueues")):
            targets = [e.target_id for e in self.repo.edges_from(eid, (rel,)) if e.target_id]
            if targets:
                out.append(f"{verb}: {', '.join(self._short(t) for t in targets[:6])}")
        return out

    def _obs_summary(self, eid: str) -> list[str]:
        out = []
        for obs in self.repo.observations_for_subjects([eid], _SUMMARY_OBS):
            if obs.kind == "raise" and obs.data.get("exc"):
                out.append(f"raises: {obs.data['exc']}")
            elif obs.kind == "except" and obs.data.get("types"):
                out.append(f"handles: {', '.join(obs.data['types'])}")
        return out

    def _short(self, eid: str) -> str:
        entity = self.repo.get_entity(eid)
        return entity.qualified_name if entity else eid

    # --- flow ----------------------------------------------------------

    def _flow(self, entity: Entity, expand_calls: int) -> Optional[FlowGraph]:
        text = self._read_file(entity.owner_file)
        if text is None:
            return None
        graph = build_flow(text, entity.name, entity.source_range.start_line, entity.qualified_name)
        if graph and expand_calls > 0:
            self._expand(graph, entity, expand_calls)
        return graph

    def _expand(self, graph: FlowGraph, entity: Entity, count: int) -> None:
        callees = [e.target_id for e in self.graph.callees(entity.id) if e.target_id]
        remaining = max(0, 18 - len(graph.nodes))
        for idx, callee_id in enumerate(callees[:count]):
            callee = self.repo.get_entity(callee_id)
            if callee is None or callee.kind not in _FUNCTION_KINDS or remaining <= 2:
                continue
            text = self._read_file(callee.owner_file)
            if text is None:
                continue
            sub = build_flow(text, callee.name, callee.source_range.start_line,
                             callee.qualified_name, node_cap=remaining)
            if sub:
                self._merge(graph, sub, callee.name, prefix=f"c{idx}_")
                remaining = max(0, 18 - len(graph.nodes))

    def _merge(self, graph: FlowGraph, sub: FlowGraph, callee_name: str, prefix: str) -> None:
        for node in sub.nodes:
            graph.nodes.append(type(node)(prefix + node.id, node.label, node.kind, node.line))
        for edge in sub.edges:
            graph.edges.append(type(edge)(prefix + edge.src, prefix + edge.dst, edge.label, edge.uncertain))
        entry = prefix + sub.nodes[0].id if sub.nodes else None
        if entry:
            for node in graph.nodes:
                if node.kind == "call" and node.label.startswith(callee_name) and not node.id.startswith(prefix):
                    graph.edges.append(type(graph.edges[0])(node.id, entry, "expand", True))
                    break

    def _read_file(self, relpath: str) -> Optional[str]:
        try:
            return self.reader(relpath, 1, 10**9)
        except OSError:
            return None
