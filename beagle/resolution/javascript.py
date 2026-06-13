"""Resolve frontend (JS/TS/Vue) API calls into backend edges.

Turns ``js_api_call`` observations into two relationships (design/14):

- ``CALLS_BACKEND`` — a call site to a backend whitelisted method, resolved by
  the dotted method path to the Python handler entity.
- ``QUERIES_DOCTYPE`` — a client-ORM or frappe-ui resource call, resolved by
  DocType name.

A literal target that cannot be resolved is kept as an unresolved edge with a
hint; a computed (non-literal) target yields no edge — the observation alone
preserves the fact, never a guess.
"""

from __future__ import annotations

from typing import Optional

from beagle.database.repository import Repository
from beagle.models import Edge, Observation
from beagle.resolution.calls import RESOLVER_VERSION
from beagle.resolution.symbols import SymbolTable


def javascript_edges(repo: Repository, table: SymbolTable) -> list[Edge]:
    by_name = _doctype_by_name(table)
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("js_api_call"):
        edge = (
            _method_edge(obs, table)
            if obs.data.get("target_kind") == "method"
            else _doctype_edge(obs, by_name)
        )
        if edge is not None:
            edges.append(edge)
    return edges


def _method_edge(obs: Observation, table: SymbolTable) -> Optional[Edge]:
    method = obs.data.get("method")
    if not method:
        return None
    target = None if obs.data.get("controller_local") else _resolve_method(table, method)
    return _edge(obs, "CALLS_BACKEND", target, method, "js-backend-call")


def _resolve_method(table: SymbolTable, dotted: str) -> Optional[str]:
    if "." not in dotted:
        return None
    return table.resolve_absolute(dotted)


def _doctype_edge(obs: Observation, by_name: dict[str, str]) -> Optional[Edge]:
    doctype = obs.data.get("doctype")
    if not doctype:
        return None
    return _edge(obs, "QUERIES_DOCTYPE", by_name.get(doctype), doctype, "js-doctype-query")


def _doctype_by_name(table: SymbolTable) -> dict[str, str]:
    out: dict[str, str] = {}
    for entity in table.entities.values():
        if entity.kind == "doctype":
            out.setdefault(entity.name, entity.id)
    return out


def _edge(
    obs: Observation, relationship: str, target: Optional[str], hint: str, resolver: str
) -> Edge:
    resolved = target is not None
    return Edge(
        source_id=obs.subject,
        relationship=relationship,
        target_id=target,
        target_hint=hint,
        confidence=0.9 if resolved else 0.0,
        resolver=resolver if resolved else "unresolved",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"api": obs.data.get("api"), "hint": hint},
    )
