"""Graph traversal and exploration queries.

Read-only operations over the resolved edge graph: resolve a name to entities,
show one entity, list relations/callers/callees, find a call path, and compute
impact. The CLI and MCP server share this service. It returns records; it does
not render or score beyond ordering by confidence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from beagle.database.repository import Repository
from beagle.models import Edge, Entity

_CALL_RELS = ("CALLS", "INVOKES", "ENQUEUES")
_DOCTYPE_ACCESS = ("READS_DOCTYPE", "WRITES_DOCTYPE", "CREATES_DOCTYPE", "DELETES_DOCTYPE")


@dataclass
class Relations:
    entity: Entity
    outgoing: list[Edge] = field(default_factory=list)
    incoming: list[Edge] = field(default_factory=list)


@dataclass
class ImpactNode:
    entity_id: str
    distance: int
    via: str


class GraphService:
    def __init__(self, repo: Repository):
        self.repo = repo

    # --- lookup --------------------------------------------------------

    def resolve(self, query: str, limit: int = 25) -> list[Entity]:
        """Resolve a name, qualified name, or entity id to entities."""
        direct = self.repo.get_entity(query)
        if direct:
            return [direct]
        return self.repo.find_entities_by_name(query, limit=limit)

    def show(self, entity_id: str) -> Optional[Entity]:
        return self.repo.get_entity(entity_id)

    def members(self, class_id: str) -> list[Entity]:
        """Methods and nested defs of a class (by stable-id prefix)."""
        return [
            e for e in self.repo.entities_by_id_prefix(class_id + ".")
            if e.kind in ("method", "function", "test_function")
        ]

    def relations(self, entity_id: str) -> Optional[Relations]:
        entity = self.repo.get_entity(entity_id)
        if entity is None:
            return None
        return Relations(
            entity=entity,
            outgoing=self.repo.edges_from(entity_id),
            incoming=self.repo.edges_to(entity_id),
        )

    def callers(self, entity_id: str) -> list[Edge]:
        return self.repo.edges_to(entity_id, _CALL_RELS)

    def callees(self, entity_id: str) -> list[Edge]:
        return [e for e in self.repo.edges_from(entity_id, _CALL_RELS) if e.target_id]

    # --- doctype-centric ----------------------------------------------

    def uses_doctype(self, doctype_id: str) -> list[Edge]:
        return self.repo.edges_to(doctype_id, _DOCTYPE_ACCESS)

    def tests(self, entity_id: str) -> list[Edge]:
        """Tests covering an entity: explicit TESTS edges plus test-fn callers."""
        edges = self.repo.edges_to(entity_id, ("TESTS",))
        for edge in self.repo.edges_to(entity_id, ("CALLS",)):
            source = self.repo.get_entity(edge.source_id)
            if source and source.kind == "test_function":
                edges.append(edge)
        return edges

    # --- traversal -----------------------------------------------------

    def path(self, source_id: str, target_id: str, max_depth: int = 8) -> Optional[list[str]]:
        """Shortest call path from source to target over call-like edges."""
        queue: deque[tuple[str, list[str]]] = deque([(source_id, [source_id])])
        seen = {source_id}
        while queue:
            node, trail = queue.popleft()
            if node == target_id:
                return trail
            if len(trail) > max_depth:
                continue
            for edge in self.repo.edges_from(node, _CALL_RELS):
                if edge.target_id and edge.target_id not in seen:
                    seen.add(edge.target_id)
                    queue.append((edge.target_id, [*trail, edge.target_id]))
        return None

    def impact(self, entity_id: str, max_depth: int = 3) -> list[ImpactNode]:
        """Entities transitively reaching ``entity_id`` (its blast radius)."""
        relations = (*_CALL_RELS, "OVERRIDES", "EXPOSES_ENDPOINT", *_DOCTYPE_ACCESS)
        result: list[ImpactNode] = []
        seen = {entity_id}
        queue: deque[tuple[str, int]] = deque([(entity_id, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.repo.edges_to(node, relations):
                if edge.source_id in seen:
                    continue
                seen.add(edge.source_id)
                result.append(ImpactNode(edge.source_id, depth + 1, edge.relationship))
                queue.append((edge.source_id, depth + 1))
        return result
