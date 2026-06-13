"""tree-sitter based JavaScript/TypeScript extractor.

Walks a parsed module and emits entities (module, class, function, method),
raw observations (imports, ``extends``, frontend API calls), and symbol chunks
for search. Records facts only; resolution turns observations into edges in a
later cross-file pass (design/14).

``line_offset`` lets a Vue ``<script>`` block report ranges in the coordinates
of the enclosing ``.vue`` file. The parser only reads text — it never executes
the source under analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from beagle.extractors.javascript import binding, frappe_api
from beagle.extractors.javascript.naming import entity_id, module_id, normalize_relpath
from beagle.models import Entity, Observation, SourceRange, TextChunk

_FUNCTION_NODES = (
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "arrow_function",
)
_FUNCTION_VALUES = ("arrow_function", "function_expression", "function")


@dataclass
class JsExtraction:
    entities: list[Entity] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    chunks: list[TextChunk] = field(default_factory=list)


def extract_javascript(
    relpath: str, text: str, language: str, line_offset: int = 0
) -> JsExtraction:
    grammar = "typescript" if language == "typescript" else "javascript"
    tree = binding.parse(grammar, text)
    out = JsExtraction()
    if tree is None:
        return out
    _Extractor(relpath, tree.source, line_offset, out).run(tree.root)
    return out


class _Extractor:
    """Recursive-descent walker carrying the current scope owner and qualname."""

    def __init__(self, relpath: str, source: bytes, line_offset: int, out: JsExtraction):
        self.relpath = normalize_relpath(relpath)
        self.source = source
        self.offset = line_offset
        self.out = out

    # --- traversal -----------------------------------------------------

    def run(self, root: object) -> None:
        module = self._module_entity(root)
        self.out.entities.append(module)
        for child in binding.named_children(root):
            self._visit(child, module.id, [])

    def _visit(self, node: object, owner: str, qual: list[str]) -> None:
        scope = self._scope_entity(node, qual)
        if scope is not None:
            self.out.entities.append(scope.entity)
            self._add_symbol_chunk(scope.entity)
            if scope.base is not None:
                self._record_inheritance(scope.entity.id, scope.base)
            for child in binding.named_children(scope.body_parent):
                self._visit(child, scope.entity.id, qual + [scope.entity.name])
            return
        if binding.kind(node) == "import_statement":
            self._record_import(node)
        elif binding.kind(node) == "call_expression":
            self._record_call(node, owner)
        for child in binding.named_children(node):
            self._visit(child, owner, qual)

    # --- entities ------------------------------------------------------

    def _module_entity(self, root: object) -> Entity:
        return Entity(
            id=module_id(self.relpath),
            kind="js_module",
            name=self.relpath.rsplit("/", 1)[-1],
            qualified_name=self.relpath,
            owner_file=self.relpath,
            source_range=self._range(root),
        )

    def _scope_entity(self, node: object, qual: list[str]) -> Optional["_Scope"]:
        node_kind = binding.kind(node)
        if node_kind == "class_declaration":
            return self._class_scope(node, qual)
        if node_kind in ("function_declaration", "generator_function_declaration"):
            return self._named_function_scope(node, qual)
        if node_kind == "method_definition":
            return self._method_scope(node, qual)
        if node_kind == "variable_declarator":
            return self._arrow_scope(node, qual)
        return None

    def _class_scope(self, node: object, qual: list[str]) -> Optional["_Scope"]:
        name = self._field_text(node, "name")
        if not name:
            return None
        body = binding.field(node, "body") or node
        entity = self._entity(node, "js_class", name, qual, self._class_signature(name, node))
        return _Scope(entity, body, self._base_class(node))

    def _named_function_scope(self, node: object, qual: list[str]) -> Optional["_Scope"]:
        name = self._field_text(node, "name")
        if not name:
            return None
        kind = "js_method" if self._in_class(qual) else "js_function"
        entity = self._entity(node, kind, name, qual, self._signature("function", name, node))
        return _Scope(entity, node, None)

    def _method_scope(self, node: object, qual: list[str]) -> Optional["_Scope"]:
        name = self._field_text(node, "name")
        if not name:
            return None
        entity = self._entity(node, "js_method", name, qual, self._signature("", name, node))
        return _Scope(entity, node, None)

    def _arrow_scope(self, node: object, qual: list[str]) -> Optional["_Scope"]:
        value = binding.field(node, "value")
        name = self._field_text(node, "name")
        if value is None or binding.kind(value) not in _FUNCTION_VALUES or not name:
            return None
        kind = "js_method" if self._in_class(qual) else "js_function"
        entity = self._entity(node, kind, name, qual, self._signature("", name, value))
        return _Scope(entity, value, None)

    def _entity(self, node, kind, name, qual, signature) -> Entity:
        qualified = ".".join(qual + [name])
        return Entity(
            id=entity_id(self.relpath, qualified),
            kind=kind,
            name=name,
            qualified_name=qualified,
            owner_file=self.relpath,
            source_range=self._range(node),
            signature=signature,
        )

    # --- observations --------------------------------------------------

    def _record_inheritance(self, class_id: str, base: str) -> None:
        self.out.observations.append(
            Observation(
                kind="js_inheritance",
                owner_file=self.relpath,
                subject=class_id,
                source_range=SourceRange.empty(),
                data={"base_name": base, "base_simple": base.rsplit(".", 1)[-1]},
            )
        )

    def _record_import(self, node: object) -> None:
        source_node = binding.field(node, "source")
        module = self._string_text(source_node) if source_node else None
        self.out.observations.append(
            Observation(
                kind="js_import",
                owner_file=self.relpath,
                subject=module_id(self.relpath),
                source_range=self._range(node),
                data={"module": module, "code": binding.text(node, self.source)},
            )
        )

    def _record_call(self, node: object, owner: str) -> None:
        func = binding.field(node, "function")
        arguments = binding.field(node, "arguments")
        if func is None or arguments is None:
            return
        target = frappe_api.detect(
            binding.text(func, self.source), binding.named_children(arguments), self.source
        )
        if target is None:
            return
        self.out.observations.append(
            Observation(
                kind="js_api_call",
                owner_file=self.relpath,
                subject=owner,
                source_range=self._range(node),
                data=target,
            )
        )

    # --- helpers -------------------------------------------------------

    def _add_symbol_chunk(self, entity: Entity) -> None:
        parts = [entity.qualified_name, entity.signature or ""]
        self.out.chunks.append(
            TextChunk(
                owner_file=self.relpath,
                entity_id=entity.id,
                kind="symbol",
                content="\n".join(p for p in parts if p),
                source_range=entity.source_range,
            )
        )

    def _range(self, node: object) -> SourceRange:
        base = binding.source_range(node)
        if not self.offset:
            return base
        return SourceRange(
            base.start_line + self.offset, base.start_col,
            base.end_line + self.offset, base.end_col,
        )

    def _field_text(self, node: object, name: str) -> Optional[str]:
        child = binding.field(node, name)
        return binding.text(child, self.source) if child is not None else None

    def _string_text(self, node: object) -> str:
        raw = binding.text(node, self.source)
        return raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'`" else raw

    def _in_class(self, qual: list[str]) -> bool:
        return bool(qual)

    def _base_class(self, node: object) -> Optional[str]:
        for child in binding.named_children(node):
            if binding.kind(child) == "class_heritage":
                bases = binding.named_children(child)
                return binding.text(bases[0], self.source) if bases else None
        return None

    def _class_signature(self, name: str, node: object) -> str:
        base = self._base_class(node)
        return f"class {name} extends {base}" if base else f"class {name}"

    def _signature(self, prefix: str, name: str, node: object) -> str:
        params = self._params_text(node)
        head = f"{prefix} {name}" if prefix else name
        return f"{head}{params}".strip()

    def _params_text(self, node: object) -> str:
        for child in binding.named_children(node):
            if binding.kind(child) == "formal_parameters":
                return binding.text(child, self.source)
        return "()"


@dataclass
class _Scope:
    """A named scope entity, where to recurse for its body, and its base class."""

    entity: Entity
    body_parent: object
    base: Optional[str]
