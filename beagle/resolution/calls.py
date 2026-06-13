"""Resolve call observations into CALLS edges.

Applies resolvers in the order design/04 prescribes: super, self/cls methods
(direct then inherited), bare names (module scope then imports), receiver type
propagation, then dotted import paths. Every call yields exactly one edge; when
nothing resolves the edge keeps ``target_id=None`` and the raw callee as a hint
so the observation is never silently dropped or upgraded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from beagle.models import Edge, Observation
from beagle.resolution.symbols import SymbolTable, split_id

RESOLVER_VERSION = "py-1"
_SELF_NAMES = ("self", "cls")


@dataclass
class _Hit:
    target_id: str
    confidence: float
    resolver: str


class CallResolver:
    """Resolves one call observation against the symbol table and type maps."""

    def __init__(
        self,
        table: SymbolTable,
        assign_by_subject: dict[str, dict[str, str]],
        self_attr_by_class: dict[str, dict[str, str]],
    ):
        self.table = table
        self.assign_by_subject = assign_by_subject
        self.self_attr_by_class = self_attr_by_class

    def resolve(self, obs: Observation) -> Edge:
        data = obs.data
        module, _ = split_id(obs.subject)
        enclosing = self.table.class_of(obs.subject)
        hit = (
            self._try_super(data, enclosing)
            or self._try_self_method(data, enclosing)
            or self._try_constructor_call(data, module)
            or self._try_bare_name(data, module)
            or self._try_type_propagation(data, obs.subject, enclosing, module)
            or self._try_dotted(data, module)
        )
        return self._edge(obs, hit)

    # --- resolvers -----------------------------------------------------

    def _try_super(self, data: dict, enclosing: Optional[str]) -> Optional[_Hit]:
        if not (data.get("super") and data.get("attr") and enclosing):
            return None
        for base in self.table.class_bases.get(enclosing, []):
            found, _ = self.table.resolve_method(base, data["attr"])
            if found:
                return _Hit(found, 0.9, "super")
        return None

    def _try_self_method(self, data: dict, enclosing: Optional[str]) -> Optional[_Hit]:
        if not (data.get("receiver_code") in _SELF_NAMES and data.get("attr") and enclosing):
            return None
        found, inherited = self.table.resolve_method(enclosing, data["attr"])
        if not found:
            return None
        if inherited:
            return _Hit(found, 0.8, "inherited-method")
        return _Hit(found, 0.9, "self-method")

    def _try_constructor_call(self, data: dict, module: str) -> Optional[_Hit]:
        """``Foo().bar()`` -> ``Foo.bar`` when ``Foo`` resolves to a class."""
        ctor = data.get("receiver_ctor")
        attr = data.get("attr")
        if not (ctor and attr):
            return None
        class_id = self._resolve_type(module, ctor)
        if not class_id:
            return None
        found, _ = self.table.resolve_method(class_id, attr)
        return _Hit(found, 0.75, "constructor-call") if found else None

    def _try_bare_name(self, data: dict, module: str) -> Optional[_Hit]:
        if data.get("attr") is not None or not data.get("head"):
            return None
        if data.get("dotted") != data.get("head"):
            return None
        name = data["head"]
        target = self.table.resolve_name(module, name)
        if not target:
            return None
        if self.table.module_members.get(module, {}).get(name) == target:
            return _Hit(target, 0.9, "module-scope")
        return _Hit(target, 0.85, "import")

    def _try_type_propagation(
        self, data: dict, subject: str, enclosing: Optional[str], module: str
    ) -> Optional[_Hit]:
        receiver = data.get("receiver_code")
        attr = data.get("attr")
        if not (receiver and attr):
            return None
        type_name = self._receiver_type(receiver, subject, enclosing)
        if not type_name:
            return None
        class_id = self._resolve_type(module, type_name)
        if not class_id:
            return None
        found, _ = self.table.resolve_method(class_id, attr)
        return _Hit(found, 0.6, "type-propagation") if found else None

    def _try_dotted(self, data: dict, module: str) -> Optional[_Hit]:
        dotted = data.get("dotted")
        if not dotted or "." not in dotted:
            return None
        target = self.table.resolve_dotted(module, dotted.split("."))
        return _Hit(target, 0.7, "dotted") if target else None

    # --- helpers -------------------------------------------------------

    def _receiver_type(
        self, receiver: str, subject: str, enclosing: Optional[str]
    ) -> Optional[str]:
        local = self.assign_by_subject.get(subject, {}).get(receiver)
        if local:
            return local
        if enclosing:
            return self.self_attr_by_class.get(enclosing, {}).get(receiver)
        return None

    def _resolve_type(self, module: str, type_name: str) -> Optional[str]:
        if "." in type_name:
            return self.table.resolve_dotted(module, type_name.split("."))
        return self.table.resolve_name(module, type_name)

    def _edge(self, obs: Observation, hit: Optional[_Hit]) -> Edge:
        if hit is None:
            return Edge(
                source_id=obs.subject,
                relationship="CALLS",
                confidence=0.0,
                resolver="unresolved",
                resolver_version=RESOLVER_VERSION,
                owner_file=obs.owner_file,
                source_range=obs.source_range,
                target_hint=obs.data.get("func_code"),
                observation_id=obs.id,
                evidence={"func_code": obs.data.get("func_code")},
            )
        return Edge(
            source_id=obs.subject,
            relationship="CALLS",
            target_id=hit.target_id,
            confidence=hit.confidence,
            resolver=hit.resolver,
            resolver_version=RESOLVER_VERSION,
            owner_file=obs.owner_file,
            source_range=obs.source_range,
            target_hint=obs.data.get("func_code"),
            observation_id=obs.id,
            evidence={"func_code": obs.data.get("func_code"), "resolver": hit.resolver},
        )
