"""In-memory symbol table built from indexed entities and observations.

Pure lookups over the graph: module members, class methods, inheritance, and
import bindings. The call resolver queries it; it performs no I/O and stores no
edges. Built once per resolution pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from beagle.database.repository import Repository
from beagle.models import Entity

_CLASS_KINDS = ("class", "test_class")
_PREFIX = "python://"


def split_id(entity_id: str) -> tuple[str, Optional[str]]:
    """Return ``(module, qualname)`` from an entity id; qualname None for a module."""
    rest = entity_id[len(_PREFIX):] if entity_id.startswith(_PREFIX) else entity_id
    if "#" in rest:
        module, qual = rest.split("#", 1)
        return module, qual
    return rest, None


def make_module_id(module: str) -> str:
    return f"{_PREFIX}{module}"


def make_entity_id(module: str, qual: str) -> str:
    return f"{_PREFIX}{module}#{qual}"


@dataclass
class ImportBinding:
    """How a name in a module's namespace maps to something importable."""

    style: str  # "module" or "from"
    module: str  # target module path (for "from", the module imported FROM)
    name: Optional[str] = None  # imported member, for "from" style


@dataclass
class SymbolTable:
    entities: dict[str, Entity] = field(default_factory=dict)
    modules: set[str] = field(default_factory=set)
    # module -> {simple_name: entity_id} for top-level classes/functions
    module_members: dict[str, dict[str, str]] = field(default_factory=dict)
    # class_id -> {member_name: entity_id} (methods and nested defs)
    class_members: dict[str, dict[str, str]] = field(default_factory=dict)
    # class_id -> [resolved base class ids]
    class_bases: dict[str, list[str]] = field(default_factory=dict)
    # module -> {bound_name: ImportBinding}
    imports: dict[str, dict[str, ImportBinding]] = field(default_factory=dict)

    def class_of(self, entity_id: str) -> Optional[str]:
        """Return the enclosing class id for a method/nested entity, if any."""
        module, qual = split_id(entity_id)
        if not qual or "." not in qual:
            return None
        parent = make_entity_id(module, qual.rsplit(".", 1)[0])
        ent = self.entities.get(parent)
        return parent if ent and ent.kind in _CLASS_KINDS else None

    def resolve_method(self, class_id: str, name: str) -> tuple[Optional[str], bool]:
        """Find ``name`` on a class or its bases. Returns (id, inherited)."""
        direct = self.class_members.get(class_id, {}).get(name)
        if direct:
            return direct, False
        for base in self.class_bases.get(class_id, []):
            found, _ = self.resolve_method(base, name)
            if found:
                return found, True
        return None, False

    def resolve_name(self, module: str, name: str) -> Optional[str]:
        """Resolve a bare name visible in ``module`` to a top-level entity."""
        local = self.module_members.get(module, {}).get(name)
        if local:
            return local
        binding = self.imports.get(module, {}).get(name)
        if binding is None:
            return None
        if binding.style == "from":
            cand = make_entity_id(binding.module, binding.name)
            if cand in self.entities:
                return cand
            submodule = f"{binding.module}.{binding.name}"
            return make_module_id(submodule) if submodule in self.modules else None
        return make_module_id(binding.module) if binding.module in self.modules else None

    def resolve_dotted(self, module: str, parts: list[str]) -> Optional[str]:
        """Resolve a dotted reference (``a.b.c``) seen in ``module``."""
        if not parts:
            return None
        head, rest = parts[0], parts[1:]
        binding = self.imports.get(module, {}).get(head)
        if binding is not None:
            return self._resolve_via_import(binding, rest)
        local = self.module_members.get(module, {}).get(head)
        if local:
            return self._resolve_member_chain(local, rest)
        return None

    def _resolve_via_import(self, binding: ImportBinding, rest: list[str]) -> Optional[str]:
        if binding.style == "from":
            entity = make_entity_id(binding.module, binding.name)
            if entity in self.entities:
                return self._resolve_member_chain(entity, rest)
            base_module = f"{binding.module}.{binding.name}"
        else:
            base_module = binding.module
        return self._resolve_in_module_path(base_module, rest)

    def _resolve_in_module_path(self, base_module: str, rest: list[str]) -> Optional[str]:
        if not rest:
            return make_module_id(base_module) if base_module in self.modules else None
        member = rest[-1]
        target_module = ".".join([base_module, *rest[:-1]]) if len(rest) > 1 else base_module
        cand = make_entity_id(target_module, member)
        if cand in self.entities:
            return cand
        submodule = f"{target_module}.{member}"
        return make_module_id(submodule) if submodule in self.modules else None

    def resolve_absolute(self, dotted: str) -> Optional[str]:
        """Resolve a fully-qualified dotted path (e.g. a job target) to an id."""
        parts = dotted.split(".")
        for tail in (1, 2):
            if len(parts) > tail:
                cand = make_entity_id(".".join(parts[:-tail]), ".".join(parts[-tail:]))
                if cand in self.entities:
                    return cand
        return make_module_id(dotted) if dotted in self.modules else None

    def _resolve_member_chain(self, entity_id: str, rest: list[str]) -> Optional[str]:
        if not rest:
            return entity_id
        ent = self.entities.get(entity_id)
        if ent and ent.kind in _CLASS_KINDS:
            found, _ = self.resolve_method(entity_id, rest[-1])
            return found
        return None
