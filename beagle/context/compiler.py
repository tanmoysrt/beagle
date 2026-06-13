"""Compile an intent-shaped context bundle for a question.

Given an intent (locate/understand/change/debug/test) and a query, seed from
lexical search and exact symbol resolution, expand over the graph according to
the intent, then select entities under per-category limits and a total token
budget. Every selected item carries why it was chosen, its confidence, exact
source range, and an excerpt — so a consumer reads only what matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from beagle.database.repository import Repository
from beagle.models import Entity
from beagle.search.engine import SearchEngine
from beagle.search.graph import GraphService

Reader = Callable[[str, int, int], str]

# Per-intent expansion plan and category caps.
_INTENTS = {
    "locate": {"callees": 0, "callers": 0, "tests": 0, "related": 0},
    "understand": {"callees": 8, "callers": 4, "tests": 2, "related": 6},
    "change": {"callees": 4, "callers": 8, "tests": 4, "related": 4},
    "debug": {"callees": 8, "callers": 6, "tests": 2, "related": 4},
    "test": {"callees": 2, "callers": 0, "tests": 8, "related": 2},
    # design/11 §11: issue-shaped context — wide downstream + upstream reach so
    # the compiled bundle spans a probable workflow, not just one symbol.
    "investigate": {"callees": 8, "callers": 6, "tests": 3, "related": 6},
}
_MAX_EXCERPT_LINES = 60


@dataclass
class ContextItem:
    entity_id: str
    kind: str
    qualified_name: str
    path: str
    start_line: int
    end_line: int
    reason: str
    confidence: float
    excerpt: str
    tokens: int


@dataclass
class ContextBundle:
    intent: str
    query: str
    items: list[ContextItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    used_tokens: int = 0
    max_tokens: int = 0


@dataclass
class _Candidate:
    entity_id: str
    priority: int
    reason: str
    confidence: float


class ContextCompiler:
    def __init__(self, repo: Repository, graph: GraphService, search: SearchEngine, reader: Reader):
        self.repo = repo
        self.graph = graph
        self.search = search
        self.reader = reader

    def compile(self, intent: str, query: str, max_tokens: int = 6000) -> ContextBundle:
        plan = _INTENTS.get(intent, _INTENTS["understand"])
        bundle = ContextBundle(intent=intent, query=query, max_tokens=max_tokens)
        if intent not in _INTENTS:
            bundle.notes.append(f"unknown intent '{intent}', used 'understand'")
        seeds = self._seed(query)
        if not seeds:
            bundle.notes.append("no seed entities; try a more specific query or a symbol name")
            return bundle
        candidates = self._expand(seeds, plan)
        self._select(bundle, candidates, plan, max_tokens)
        return bundle

    # --- seeding -------------------------------------------------------

    def _seed(self, query: str) -> list[_Candidate]:
        seen: dict[str, _Candidate] = {}
        for entity in self._resolve_tokens(query):
            seen.setdefault(entity.id, _Candidate(entity.id, 0, "matches query symbol", 1.0))
        # Lexical hits are noisier than exact symbols, so use them only to fill
        # in when few symbols resolved; otherwise the graph drives selection and
        # lexical noise (any chunk mentioning the term) is kept out.
        sparse = len(seen) < 2
        for rank, result in enumerate(self.search.search(query, limit=15)):
            eid = result.entity_id
            if not eid or eid in seen:
                continue
            if sparse:
                seen[eid] = _Candidate(eid, 0, "lexical search hit", max(0.5, 1.0 - rank * 0.05))
        return list(seen.values())

    def _resolve_tokens(self, query: str) -> list[Entity]:
        out: list[Entity] = []
        tokens = {t.strip(".,?()\"'") for t in query.split()}
        for token in tokens:
            if len(token) < 3 or token.islower():
                continue
            out.extend(self.graph.resolve(token, limit=3))
        return out

    # --- expansion -----------------------------------------------------

    def _expand(self, seeds: list[_Candidate], plan: dict) -> list[_Candidate]:
        candidates = {c.entity_id: c for c in seeds}
        for seed in seeds:
            self._add_members(candidates, seed.entity_id)
            if plan["callees"]:
                self._add_edges(candidates, self.graph.callees(seed.entity_id), 1, "called by seed", "target_id", plan["callees"])
            if plan["callers"]:
                self._add_edges(candidates, self.graph.callers(seed.entity_id), 1, "calls seed", "source_id", plan["callers"])
            if plan["tests"]:
                self._add_edges(candidates, self.graph.tests(seed.entity_id), 2, "tests seed", "source_id", plan["tests"])
            if plan["related"]:
                self._add_related(candidates, seed.entity_id, plan["related"])
        return list(candidates.values())

    def _add_members(self, candidates, entity_id: str) -> None:
        """Pull a seed class's methods, and a seed DocType's controller methods."""
        entity = self.repo.get_entity(entity_id)
        if entity is None:
            return
        class_ids: list[str] = []
        if entity.kind in ("class", "test_class"):
            class_ids.append(entity_id)
        elif entity.kind == "doctype":
            for edge in self.repo.edges_from(entity_id, ("HAS_CONTROLLER",)):
                if edge.target_id:
                    class_ids.append(edge.target_id)
                    candidates.setdefault(edge.target_id,
                                          _Candidate(edge.target_id, 1, "controller of seed DocType", edge.confidence))
        for class_id in class_ids:
            for member in self.graph.members(class_id):
                candidates.setdefault(member.id, _Candidate(member.id, 1, "method of seed class", 0.95))

    def _add_edges(self, candidates, edges, priority, reason, which, limit) -> None:
        for edge in edges[:limit]:
            other = edge.target_id if which == "target_id" else edge.source_id
            if other and other not in candidates:
                candidates[other] = _Candidate(other, priority, reason, edge.confidence)

    def _add_related(self, candidates, entity_id, limit) -> None:
        rels = ("HAS_CONTROLLER", "INHERITS", "INVOKES", "READS_DOCTYPE",
                "WRITES_DOCTYPE", "CREATES_DOCTYPE", "LINKS_TO", "CONTAINS_CHILD",
                "HAS_FIELD", "OVERRIDES")
        count = 0
        for edge in self.repo.edges_from(entity_id, rels) + self.repo.edges_to(entity_id, rels):
            if count >= limit:
                break
            other = edge.target_id if edge.source_id == entity_id else edge.source_id
            if other and other not in candidates:
                candidates[other] = _Candidate(other, 2, f"related via {edge.relationship}", edge.confidence)
                count += 1

    # --- selection -----------------------------------------------------

    def _select(self, bundle: ContextBundle, candidates: list[_Candidate], plan: dict, max_tokens: int) -> None:
        candidates.sort(key=lambda c: (c.priority, -c.confidence))
        for cand in candidates:
            entity = self.repo.get_entity(cand.entity_id)
            if entity is None or entity.kind in ("endpoint", "background_job"):
                # endpoint/job entities point at a handler with no readable body
                # of their own; the handler function is included via its edge.
                continue
            item = self._build_item(entity, cand)
            if bundle.used_tokens + item.tokens > max_tokens and bundle.items:
                bundle.notes.append("token budget reached; some related entities omitted")
                break
            bundle.items.append(item)
            bundle.used_tokens += item.tokens

    def _build_item(self, entity: Entity, cand: _Candidate) -> ContextItem:
        excerpt = self._excerpt(entity)
        return ContextItem(
            entity_id=entity.id,
            kind=entity.kind,
            qualified_name=entity.qualified_name,
            path=entity.owner_file,
            start_line=entity.source_range.start_line,
            end_line=entity.source_range.end_line,
            reason=cand.reason,
            confidence=cand.confidence,
            excerpt=excerpt,
            tokens=max(1, len(excerpt) // 4),
        )

    def _excerpt(self, entity: Entity) -> str:
        if entity.kind in ("module", "doctype", "class", "test_class"):
            head = entity.signature or entity.qualified_name
            return f"{head}\n{entity.docstring or ''}".strip()
        start = entity.source_range.start_line
        end = min(entity.source_range.end_line, start + _MAX_EXCERPT_LINES - 1)
        try:
            return self.reader(entity.owner_file, start, end)
        except OSError:
            return entity.signature or entity.qualified_name
