"""Construct a SymbolTable from the indexed graph.

Loads entities and the import/inheritance observations, then resolves base
classes so the table can answer method lookups across inheritance.
"""

from __future__ import annotations

from beagle.database.repository import Repository
from beagle.models import Entity
from beagle.resolution.symbols import (
    ImportBinding,
    SymbolTable,
    make_entity_id,
    split_id,
)

_CLASS_KINDS = ("class", "test_class")


def build_symbol_table(repo: Repository) -> SymbolTable:
    table = SymbolTable()
    _load_entities(table, repo.iter_entities())
    _load_imports(table, repo)
    _resolve_bases(table, repo)
    return table


def _load_entities(table: SymbolTable, entities: list[Entity]) -> None:
    for entity in entities:
        table.entities[entity.id] = entity
        module, qual = split_id(entity.id)
        if qual is None:
            table.modules.add(module)
            continue
        if "." not in qual:
            table.module_members.setdefault(module, {})[qual] = entity.id
        else:
            parent = make_entity_id(module, qual.rsplit(".", 1)[0])
            name = qual.rsplit(".", 1)[1]
            table.class_members.setdefault(parent, {})[name] = entity.id


def _load_imports(table: SymbolTable, repo: Repository) -> None:
    for obs in repo.observations_of_kind("import"):
        module, _ = split_id(obs.subject)
        bindings = table.imports.setdefault(module, {})
        if obs.data.get("style") == "import":
            _bind_import(bindings, obs.data)
        else:
            _bind_from(bindings, module, obs.data)


def _bind_import(bindings: dict[str, ImportBinding], data: dict) -> None:
    target = data.get("module")
    if not target:
        return
    asname = data.get("asname")
    bound = asname or target.split(".", 1)[0]
    refers = target if asname else target.split(".", 1)[0]
    bindings[bound] = ImportBinding(style="module", module=refers)


def _bind_from(bindings: dict[str, ImportBinding], module: str, data: dict) -> None:
    target_module = _absolute_module(module, data.get("module"), data.get("level", 0))
    for entry in data.get("names", []):
        name = entry.get("name")
        if not name or name == "*":
            continue
        bound = entry.get("asname") or name
        bindings[bound] = ImportBinding(style="from", module=target_module, name=name)


def _absolute_module(current: str, module: str | None, level: int) -> str:
    """Resolve a possibly-relative ``from`` import to an absolute module path."""
    if level == 0:
        return module or ""
    base_parts = current.split(".")[: -level] if level else current.split(".")
    base = ".".join(base_parts)
    return f"{base}.{module}" if module else base


def _resolve_bases(table: SymbolTable, repo: Repository) -> None:
    for obs in repo.observations_of_kind("inheritance"):
        class_id = obs.subject
        module, _ = split_id(class_id)
        base_id = _resolve_base(table, module, obs.data)
        if base_id and table.entities.get(base_id) and \
                table.entities[base_id].kind in _CLASS_KINDS:
            table.class_bases.setdefault(class_id, []).append(base_id)


def _resolve_base(table: SymbolTable, module: str, data: dict) -> str | None:
    dotted = data.get("base_dotted")
    if dotted and "." in dotted:
        return table.resolve_dotted(module, dotted.split("."))
    name = data.get("base_name")
    return table.resolve_name(module, name) if name else None
