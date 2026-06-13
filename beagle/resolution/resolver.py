"""Cross-file resolution pass.

Turns raw observations into resolved edges. Runs after extraction so name
lookups see entities from every file. The whole edge set is recomputed each
pass (delete-then-rebuild), which keeps incremental updates free of stale
edges. Resolution never invents a confirmed fact: unresolved targets are kept
with ``target_id=None`` and a hint.
"""

from __future__ import annotations

from beagle.database import Database
from beagle.database.repository import Repository
from beagle.models import Edge, Observation
from beagle.resolution.builder import build_symbol_table, _absolute_module
from beagle.resolution.calls import RESOLVER_VERSION, CallResolver
from beagle.resolution.frappe import frappe_edges
from beagle.resolution.symbols import SymbolTable, make_entity_id, make_module_id, split_id


def resolve_workspace(db: Database, repo: Repository) -> None:
    table = build_symbol_table(repo)
    assign_by_subject, self_attr_by_class = _build_type_maps(repo, table)
    caller = CallResolver(table, assign_by_subject, self_attr_by_class)

    edges: list[Edge] = []
    edges += _import_edges(repo, table)
    edges += _inheritance_edges(repo, table)
    edges += _override_edges(table)
    edges += frappe_edges(repo, table)
    edges += [caller.resolve(o) for o in repo.observations_of_kind("call")]

    with db.transaction() as conn:
        repo.delete_all_edges(conn)
        repo.insert_edges(conn, edges)


# --- type maps for receiver inference ----------------------------------


def _build_type_maps(
    repo: Repository, table: SymbolTable
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_subject: dict[str, dict[str, str]] = {}
    self_attr: dict[str, dict[str, str]] = {}
    for obs in repo.observations_of_kind("assignment"):
        type_name = obs.data.get("value_callee") or obs.data.get("annotation")
        target = obs.data.get("target_code")
        if not type_name or not target:
            continue
        by_subject.setdefault(obs.subject, {})[target] = type_name
        if target.startswith("self."):
            cls = table.class_of(obs.subject)
            if cls:
                self_attr.setdefault(cls, {})[target] = type_name
    return by_subject, self_attr


# --- import edges ------------------------------------------------------


def _import_edges(repo: Repository, table: SymbolTable) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("import"):
        module, _ = split_id(obs.subject)
        if obs.data.get("style") == "import":
            edges.append(_import_module_edge(obs, table))
        else:
            edges += _from_import_edges(obs, module, table)
    return edges


def _import_module_edge(obs: Observation, table: SymbolTable) -> Edge:
    target = obs.data.get("module") or ""
    resolved = make_module_id(target) if target in table.modules else None
    return _named_edge(obs, "IMPORTS", resolved, target, "import")


def _from_import_edges(obs: Observation, module: str, table: SymbolTable) -> list[Edge]:
    target_module = _absolute_module(module, obs.data.get("module"), obs.data.get("level", 0))
    edges: list[Edge] = []
    for entry in obs.data.get("names", []):
        name = entry.get("name")
        if not name or name == "*":
            continue
        resolved = _resolve_from_target(table, target_module, name)
        edges.append(_named_edge(obs, "IMPORTS", resolved, f"{target_module}.{name}", "import"))
    return edges


def _resolve_from_target(table: SymbolTable, target_module: str, name: str) -> str | None:
    entity = make_entity_id(target_module, name)
    if entity in table.entities:
        return entity
    submodule = f"{target_module}.{name}"
    if submodule in table.modules:
        return make_module_id(submodule)
    return make_module_id(target_module) if target_module in table.modules else None


# --- inheritance and overrides -----------------------------------------


def _inheritance_edges(repo: Repository, table: SymbolTable) -> list[Edge]:
    edges: list[Edge] = []
    for obs in repo.observations_of_kind("inheritance"):
        module, _ = split_id(obs.subject)
        dotted = obs.data.get("base_dotted")
        if dotted and "." in dotted:
            target = table.resolve_dotted(module, dotted.split("."))
        else:
            target = table.resolve_name(module, obs.data.get("base_name") or "")
        edges.append(_named_edge(obs, "INHERITS", target, obs.data.get("base_code"), "inheritance"))
    return edges


def _override_edges(table: SymbolTable) -> list[Edge]:
    edges: list[Edge] = []
    for class_id, members in table.class_members.items():
        bases = table.class_bases.get(class_id, [])
        if not bases:
            continue
        for name, method_id in members.items():
            base_method = _lookup_in_bases(table, bases, name)
            if base_method:
                edges.append(_override_edge(table, method_id, base_method))
    return edges


def _lookup_in_bases(table: SymbolTable, bases: list[str], name: str) -> str | None:
    for base in bases:
        found, _ = table.resolve_method(base, name)
        if found:
            return found
    return None


def _override_edge(table: SymbolTable, method_id: str, base_method: str) -> Edge:
    entity = table.entities[method_id]
    return Edge(
        source_id=method_id,
        relationship="OVERRIDES",
        target_id=base_method,
        confidence=0.9,
        resolver="override",
        resolver_version=RESOLVER_VERSION,
        owner_file=entity.owner_file,
        source_range=entity.source_range,
        evidence={"method": entity.qualified_name},
    )


# --- shared edge construction ------------------------------------------


def _named_edge(
    obs: Observation, relationship: str, target: str | None, hint: str | None, resolver: str
) -> Edge:
    resolved = target is not None
    return Edge(
        source_id=obs.subject,
        relationship=relationship,
        target_id=target,
        target_hint=hint,
        confidence=1.0 if resolved else 0.0,
        resolver=resolver if resolved else "unresolved",
        resolver_version=RESOLVER_VERSION,
        owner_file=obs.owner_file,
        source_range=obs.source_range,
        observation_id=obs.id,
        evidence={"hint": hint},
    )
