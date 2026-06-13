"""LibCST-based Python extractor.

Walks a parsed module and emits entities (module/class/function/method, plus
test variants), raw observations (imports, inheritance, assignments, calls),
and symbol chunks for search. It records facts only — no resolution happens
here, so ambiguous calls are preserved verbatim for the resolver.

Never imports or executes the file under analysis; LibCST parses text only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from beagle.extractors.python.expressions import dotted_name, head_name, is_super_call
from beagle.extractors.python.naming import entity_id, module_id, module_path_for
from beagle.models import Entity, Observation, SourceRange, TextChunk


@dataclass
class _Frame:
    kind: str
    name: str
    id: str


@dataclass
class PythonExtraction:
    entities: list[Entity] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    chunks: list[TextChunk] = field(default_factory=list)


def extract_python(relpath: str, text: str, module: Optional[str] = None) -> PythonExtraction:
    if module is None:
        module = module_path_for(relpath)
    try:
        wrapper = MetadataWrapper(cst.parse_module(text))
    except cst.ParserSyntaxError:
        return PythonExtraction()
    visitor = _Visitor(relpath, module, wrapper.module)
    wrapper.visit(visitor)
    return visitor.out


def _is_test_class(name: str, bases: list[str]) -> bool:
    return name.startswith("Test") or any(b.endswith("TestCase") for b in bases)


def _is_test_function(name: str) -> bool:
    return name.startswith("test_") or name == "test"


def _first_string_arg(args: list[cst.Arg]) -> Optional[str]:
    """The first positional string-literal argument, if any.

    Frappe ORM and job APIs take the DocType name or dotted method path as their
    first positional string (``frappe.get_doc("Site")``), so the resolver maps
    these to DocType/job targets in stage 5.
    """
    for arg in args:
        if arg.keyword is not None or isinstance(arg.star, str) and arg.star:
            continue
        if isinstance(arg.value, cst.SimpleString):
            value = arg.value.evaluated_value
            return value if isinstance(value, str) else None
        return None
    return None


def _exception_types(node: Optional[cst.BaseExpression]) -> list[str]:
    if node is None:
        return []
    if isinstance(node, cst.Tuple):
        return [name for el in node.elements
                if (name := dotted_name(el.value) or head_name(el.value))]
    name = dotted_name(node) or head_name(node)
    return [name] if name else []


def _num_value(node: cst.BaseExpression) -> Optional[str]:
    if isinstance(node, (cst.Integer, cst.Float)):
        return node.value
    if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus):
        inner = _num_value(node.expression)
        return f"-{inner}" if inner is not None else None
    return None


def _slice_header(header: str) -> str:
    """Take ``name(params) -> ret`` from a function header, dropping the body.

    Stops at the header colon: the first ``:`` at paren-depth 0 after the
    parameter list, so annotations and lambda defaults inside the parens don't
    end it early. Whitespace (including line breaks) is collapsed.
    """
    depth = 0
    seen_paren = False
    end = None
    for i, ch in enumerate(header):
        if ch == "(":
            depth += 1
            seen_paren = True
        elif ch == ")":
            depth -= 1
        elif ch == ":" and seen_paren and depth == 0:
            end = i
            break
    body = header[:end] if end is not None else header.split("\n", 1)[0]
    return " ".join(body.split())


class _Visitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, relpath: str, module: str, module_node: cst.Module):
        super().__init__()
        self.relpath = relpath
        self.module = module
        self.code = module_node
        self.out = PythonExtraction()
        self.scopes: list[_Frame] = []
        self.owners: list[str] = []

    # --- helpers -------------------------------------------------------

    def _range(self, node: cst.CSTNode) -> SourceRange:
        r = self.get_metadata(PositionProvider, node)
        return SourceRange(r.start.line, r.start.column, r.end.line, r.end.column)

    def _src(self, node: cst.CSTNode) -> str:
        return self.code.code_for_node(node).strip()

    @property
    def _qualname(self) -> str:
        return ".".join(f.name for f in self.scopes)

    @property
    def _owner(self) -> str:
        return self.owners[-1]

    @property
    def _in_class(self) -> bool:
        return bool(self.scopes) and self.scopes[-1].kind in ("class", "test_class")

    def _make_id(self, qualname: str) -> str:
        return entity_id(self.module, qualname)

    def _add_symbol_chunk(self, entity: Entity) -> None:
        parts = [entity.qualified_name, entity.signature or "", entity.docstring or ""]
        self.out.chunks.append(
            TextChunk(
                owner_file=self.relpath,
                entity_id=entity.id,
                kind="symbol",
                content="\n".join(p for p in parts if p),
                source_range=entity.source_range,
            )
        )

    # --- module --------------------------------------------------------

    def visit_Module(self, node: cst.Module) -> bool:
        mid = module_id(self.module)
        self.out.entities.append(
            Entity(
                id=mid,
                kind="module",
                name=self.module.rsplit(".", 1)[-1],
                qualified_name=self.module,
                owner_file=self.relpath,
                source_range=self._range(node),
                docstring=node.get_docstring(clean=True),
            )
        )
        self.owners.append(mid)
        return True

    # --- classes -------------------------------------------------------

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        bases = [self._src(b.value) for b in node.bases]
        name = node.name.value
        kind = "test_class" if _is_test_class(name, bases) else "class"
        qualname = ".".join([*(f.name for f in self.scopes), name])
        eid = self._make_id(qualname)
        entity = Entity(
            id=eid,
            kind=kind,
            name=name,
            qualified_name=f"{self.module}.{qualname}",
            owner_file=self.relpath,
            source_range=self._range(node),
            signature=self._class_signature(node, bases),
            docstring=node.get_docstring(clean=True),
            extra={"decorators": [self._src(d.decorator) for d in node.decorators]},
        )
        self.out.entities.append(entity)
        self._add_symbol_chunk(entity)
        self._record_bases(eid, node)
        self.scopes.append(_Frame(kind, name, eid))
        self.owners.append(eid)
        return True

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        self.scopes.pop()
        self.owners.pop()

    def _class_signature(self, node: cst.ClassDef, bases: list[str]) -> str:
        name = node.name.value
        return f"class {name}({', '.join(bases)})" if bases else f"class {name}"

    def _record_bases(self, class_id: str, node: cst.ClassDef) -> None:
        for base in node.bases:
            self.out.observations.append(
                Observation(
                    kind="inheritance",
                    owner_file=self.relpath,
                    subject=class_id,
                    source_range=self._range(base.value),
                    data={
                        "base_code": self._src(base.value),
                        "base_dotted": dotted_name(base.value),
                        "base_name": head_name(base.value),
                    },
                )
            )

    # --- functions -----------------------------------------------------

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        kind = self._function_kind(node.name.value)
        qualname = ".".join([*(f.name for f in self.scopes), node.name.value])
        eid = self._make_id(qualname)
        entity = Entity(
            id=eid,
            kind=kind,
            name=node.name.value,
            qualified_name=f"{self.module}.{qualname}",
            owner_file=self.relpath,
            source_range=self._range(node),
            signature=self._function_signature(node),
            docstring=node.get_docstring(clean=True),
            extra={"decorators": [self._src(d.decorator) for d in node.decorators]},
        )
        self.out.entities.append(entity)
        self._add_symbol_chunk(entity)
        self.scopes.append(_Frame(kind, node.name.value, eid))
        self.owners.append(eid)
        return True

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scopes.pop()
        self.owners.pop()

    def _function_kind(self, name: str) -> str:
        if _is_test_function(name):
            return "test_function"
        return "method" if self._in_class else "function"

    def _function_signature(self, node: cst.FunctionDef) -> str:
        # LibCST cannot codegen a detached Parameters node, so read the header
        # straight from the function source: from ``def`` to the body colon.
        full = self._src(node)
        start = full.find("def ")
        header = full[start + len("def "):] if start >= 0 else full
        return _slice_header(header)

    # --- imports -------------------------------------------------------

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            self.out.observations.append(
                Observation(
                    kind="import",
                    owner_file=self.relpath,
                    subject=module_id(self.module),
                    source_range=self._range(node),
                    data={
                        "style": "import",
                        "module": dotted_name(alias.name),
                        "asname": alias.asname.name.value
                        if alias.asname and isinstance(alias.asname.name, cst.Name)
                        else None,
                    },
                )
            )

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        names = self._import_from_names(node)
        self.out.observations.append(
            Observation(
                kind="import",
                owner_file=self.relpath,
                subject=module_id(self.module),
                source_range=self._range(node),
                data={
                    "style": "from",
                    "module": dotted_name(node.module) if node.module else None,
                    "level": len(node.relative),
                    "names": names,
                },
            )
        )

    def _import_from_names(self, node: cst.ImportFrom) -> list[dict]:
        if isinstance(node.names, cst.ImportStar):
            return [{"name": "*", "asname": None}]
        out = []
        for alias in node.names:
            asname = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else None
            )
            out.append({"name": dotted_name(alias.name), "asname": asname})
        return out

    # --- assignments ---------------------------------------------------

    def visit_Assign(self, node: cst.Assign) -> None:
        if not node.targets:
            return
        self._record_assignment(node.targets[0].target, node.value, "assign", None)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        annotation = self._src(node.annotation.annotation)
        self._record_assignment(node.target, node.value, "annassign", annotation)

    def _record_assignment(
        self,
        target: cst.BaseExpression,
        value: Optional[cst.BaseExpression],
        kind: str,
        annotation: Optional[str],
    ) -> None:
        call_callee = None
        if isinstance(value, cst.Call):
            call_callee = dotted_name(value.func)
        self.out.observations.append(
            Observation(
                kind="assignment",
                owner_file=self.relpath,
                subject=self._owner,
                source_range=self._range(target),
                data={
                    "style": kind,
                    "target_code": self._src(target),
                    "annotation": annotation,
                    "value_callee": call_callee,
                    "value_code": self._src(value) if value is not None else None,
                },
            )
        )

    # --- calls ---------------------------------------------------------

    def visit_Call(self, node: cst.Call) -> None:
        func = node.func
        if isinstance(func, cst.Name) and func.value == "super":
            return
        self.out.observations.append(
            Observation(
                kind="call",
                owner_file=self.relpath,
                subject=self._owner,
                source_range=self._range(node),
                data=self._call_data(func, node.args),
            )
        )

    def _call_data(self, func: cst.BaseExpression, args: list[cst.Arg]) -> dict:
        attr = func.attr.value if isinstance(func, cst.Attribute) else None
        receiver = func.value if isinstance(func, cst.Attribute) else None
        receiver_ctor = (
            dotted_name(receiver.func) if isinstance(receiver, cst.Call) else None
        )
        return {
            "func_code": self._src(func),
            "dotted": dotted_name(func),
            "head": head_name(func),
            "attr": attr,
            "receiver_code": self._src(receiver) if receiver is not None else None,
            "receiver_ctor": receiver_ctor,
            "super": is_super_call(receiver) if receiver is not None else False,
            "args": len(args),
            "first_arg": _first_string_arg(args),
        }

    # --- control / failure signals (for investigate and explain) -------

    def visit_Raise(self, node: cst.Raise) -> None:
        if node.exc is None:
            return
        exc = node.exc
        func = exc.func if isinstance(exc, cst.Call) else exc
        message = _first_string_arg(exc.args) if isinstance(exc, cst.Call) else None
        self.out.observations.append(
            Observation(
                kind="raise",
                owner_file=self.relpath,
                subject=self._owner,
                source_range=self._range(node),
                data={"exc": dotted_name(func) or head_name(func), "message": message},
            )
        )

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        self.out.observations.append(
            Observation(
                kind="except",
                owner_file=self.relpath,
                subject=self._owner,
                source_range=self._range(node),
                data={"types": _exception_types(node.type)},
            )
        )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        for target in node.comparisons:
            signal = self._numeric_comparison(node.left, target)
            if signal:
                self.out.observations.append(
                    Observation(
                        kind="comparison",
                        owner_file=self.relpath,
                        subject=self._owner,
                        source_range=self._range(node),
                        data=signal,
                    )
                )

    def _numeric_comparison(self, left: cst.BaseExpression, target) -> Optional[dict]:
        op = type(target.operator).__name__
        right_value = _num_value(target.comparator)
        if right_value is not None:
            return {"left_code": self._src(left), "op": op, "value": right_value}
        left_value = _num_value(left)
        if left_value is not None:
            return {"left_code": self._src(target.comparator), "op": op, "value": left_value}
        return None

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self.out.observations.append(
            Observation(
                kind="counter",
                owner_file=self.relpath,
                subject=self._owner,
                source_range=self._range(node),
                data={
                    "target_code": self._src(node.target),
                    "op": type(node.operator).__name__,
                    "value_code": self._src(node.value),
                },
            )
        )
