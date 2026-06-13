"""Build a simplified flow graph for one function from its CST.

This is an explanation view, not a full control-flow graph (design/08): it keeps
the statements that matter for understanding — branches, loops, calls, returns,
raises, try/except, status writes, DocType ops, and enqueued jobs — chained in
source order with explicit yes/no edges on conditionals. Topology is
deterministic and every node maps to a source line. Node count is capped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from beagle.extractors.python.expressions import dotted_name, head_name

_ORM = {
    "frappe.get_doc": "reads", "frappe.get_all": "reads", "frappe.get_list": "reads",
    "frappe.get_value": "reads", "frappe.db.get_value": "reads", "frappe.db.get_all": "reads",
    "frappe.new_doc": "creates", "frappe.db.set_value": "writes",
    "frappe.delete_doc": "deletes", "frappe.db.delete": "deletes",
}
_ENQUEUE = {"frappe.enqueue", "frappe.enqueue_doc"}
_MAX_LABEL = 42


@dataclass
class FlowNode:
    id: str
    label: str
    kind: str  # entry|call|branch|loop|except|raise|return|state|doctype|job
    line: int


@dataclass
class FlowEdge:
    src: str
    dst: str
    label: str = ""
    uncertain: bool = False


@dataclass
class FlowGraph:
    title: str
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    truncated: bool = False


def find_function(module: cst.Module, name: str, start_line: int, positions) -> Optional[cst.FunctionDef]:
    found: list[cst.FunctionDef] = []

    class _Finder(cst.CSTVisitor):
        def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
            if node.name.value == name and positions[node].start.line == start_line:
                found.append(node)

    module.visit(_Finder())
    return found[0] if found else None


def build_flow(file_text: str, name: str, start_line: int, title: str, node_cap: int = 18) -> Optional[FlowGraph]:
    wrapper = MetadataWrapper(cst.parse_module(file_text))
    positions = wrapper.resolve(PositionProvider)
    func = find_function(wrapper.module, name, start_line, positions)
    if func is None:
        return None
    builder = _Builder(wrapper.module, positions, title, node_cap)
    return builder.build(func)


class _Builder:
    def __init__(self, module: cst.Module, positions, title: str, node_cap: int):
        self.code = module
        self.pos = positions
        self.graph = FlowGraph(title=title)
        self.cap = node_cap
        self._n = 0

    def build(self, func: cst.FunctionDef) -> FlowGraph:
        entry = self._node(f"{func.name.value}()", "entry", func)
        exits = self._walk(func.body.body, [entry])
        end = self._node("end", "return", func)
        for src in exits:
            self._edge(src, end)
        return self.graph

    # --- helpers -------------------------------------------------------

    def _line(self, node: cst.CSTNode) -> int:
        return self.pos[node].start.line

    def _src(self, node: cst.CSTNode) -> str:
        return self.code.code_for_node(node).strip()

    def _label(self, text: str) -> str:
        text = " ".join(text.split())
        return text if len(text) <= _MAX_LABEL else text[: _MAX_LABEL - 1] + "…"

    def _node(self, label: str, kind: str, at: cst.CSTNode) -> str:
        nid = f"n{self._n}"
        self._n += 1
        self.graph.nodes.append(FlowNode(nid, self._label(label), kind, self._line(at)))
        return nid

    def _edge(self, src: str, dst: str, label: str = "", uncertain: bool = False) -> None:
        self.graph.edges.append(FlowEdge(src, dst, label, uncertain))

    @property
    def _full(self) -> bool:
        if self._n >= self.cap:
            self.graph.truncated = True
            return True
        return False

    # --- walk ----------------------------------------------------------

    def _walk(self, statements, frontier: list[str]) -> list[str]:
        for stmt in statements:
            if self._full:
                break
            frontier = self._statement(stmt, frontier)
        return frontier

    def _statement(self, stmt, frontier: list[str]) -> list[str]:
        if isinstance(stmt, cst.If):
            return self._if(stmt, frontier)
        if isinstance(stmt, (cst.For, cst.While)):
            return self._loop(stmt, frontier)
        if isinstance(stmt, cst.Try):
            return self._try(stmt, frontier)
        if isinstance(stmt, cst.SimpleStatementLine):
            return self._simple(stmt, frontier)
        if isinstance(stmt, (cst.FunctionDef, cst.ClassDef)):
            return frontier  # skip nested defs in the flow view
        return frontier

    def _if(self, stmt: cst.If, frontier: list[str]) -> list[str]:
        cond = self._node(f"if {self._src(stmt.test)}", "branch", stmt)
        for src in frontier:
            self._edge(src, cond)
        then_exits = self._walk(stmt.body.body, [cond])
        self._relabel_first_edge(cond, "yes")
        else_exits = self._else(stmt.orelse, cond)
        return then_exits + (else_exits if else_exits else [cond])

    def _else(self, orelse, cond: str) -> list[str]:
        if orelse is None:
            return []
        body = orelse.body.body if isinstance(orelse, cst.Else) else [orelse]
        exits = self._walk(body, [cond])
        # tag the branch edge into the else as "no"
        for edge in self.graph.edges:
            if edge.src == cond and edge.label == "" and edge.dst != self._first_yes(cond):
                edge.label = "no"
                break
        return exits

    def _first_yes(self, cond: str) -> Optional[str]:
        for edge in self.graph.edges:
            if edge.src == cond and edge.label == "yes":
                return edge.dst
        return None

    def _relabel_first_edge(self, cond: str, label: str) -> None:
        for edge in self.graph.edges:
            if edge.src == cond and edge.label == "":
                edge.label = label
                return

    def _loop(self, stmt, frontier: list[str]) -> list[str]:
        iterable = stmt.iter if isinstance(stmt, cst.For) else stmt.test
        loop = self._node(f"loop {self._src(iterable)}", "loop", stmt)
        for src in frontier:
            self._edge(src, loop)
        body_exits = self._walk(stmt.body.body, [loop])
        for src in body_exits:
            self._edge(src, loop, "repeat")
        return [loop]

    def _try(self, stmt: cst.Try, frontier: list[str]) -> list[str]:
        body_exits = self._walk(stmt.body.body, frontier)
        exits = list(body_exits)
        for handler in stmt.handlers:
            label = "except " + (self._src(handler.type) if handler.type else "")
            node = self._node(label, "except", handler)
            for src in frontier:
                self._edge(src, node, "error", uncertain=True)
            exits += self._walk(handler.body.body, [node])
        return exits

    def _simple(self, stmt: cst.SimpleStatementLine, frontier: list[str]) -> list[str]:
        for small in stmt.body:
            node = self._small_statement(small, stmt, frontier)
            if node is not None:
                frontier = [node]
        return frontier

    def _small_statement(self, small, stmt, frontier) -> Optional[str]:
        if isinstance(small, cst.Return):
            return self._terminal(f"return {self._src(small.value) if small.value else ''}", "return", stmt, frontier)
        if isinstance(small, cst.Raise):
            exc = small.exc.func if isinstance(small.exc, cst.Call) else small.exc
            return self._terminal(f"raise {self._src(exc) if exc else ''}", "raise", stmt, frontier)
        call = self._find_call(small)
        if call is not None:
            return self._call_node(call, small, stmt, frontier)
        return None

    def _terminal(self, label, kind, stmt, frontier) -> str:
        node = self._node(label, kind, stmt)
        for src in frontier:
            self._edge(src, node)
        return node  # callers add the terminal to exits via frontier replacement

    def _find_call(self, small) -> Optional[cst.Call]:
        if isinstance(small, cst.Expr) and isinstance(small.value, cst.Call):
            return small.value
        if isinstance(small, (cst.Assign, cst.AnnAssign)) and isinstance(small.value, cst.Call):
            return small.value
        return None

    def _call_node(self, call: cst.Call, small, stmt, frontier) -> str:
        dotted = dotted_name(call.func)
        kind, label = self._classify_call(call, dotted, small)
        uncertain = dotted is None and not _is_self_call(call.func)
        node = self._node(label, kind, stmt)
        for src in frontier:
            self._edge(src, node, uncertain=uncertain)
        return node

    def _classify_call(self, call, dotted, small) -> tuple[str, str]:
        first = _first_string(call.args)
        if dotted in _ORM:
            return "doctype", f"{_ORM[dotted]} {first or '?'}"
        if dotted in _ENQUEUE:
            return "job", f"enqueue {first or '?'}"
        if isinstance(small, (cst.Assign, cst.AnnAssign)):
            target = self._assign_target(small)
            if target and target.endswith((".status", ".state")):
                return "state", f"set {target}"
        return "call", f"{self._src(call.func)}()"

    def _assign_target(self, small) -> Optional[str]:
        if isinstance(small, cst.Assign) and small.targets:
            return self._src(small.targets[0].target)
        if isinstance(small, cst.AnnAssign):
            return self._src(small.target)
        return None


def _is_self_call(func) -> bool:
    return isinstance(func, cst.Attribute) and head_name(func) in ("self", "cls")


def _first_string(args) -> Optional[str]:
    for arg in args:
        if arg.keyword is None and isinstance(arg.value, cst.SimpleString):
            value = arg.value.evaluated_value
            return value if isinstance(value, str) else None
        if arg.keyword is None:
            return None
    return None
