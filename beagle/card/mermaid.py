"""Render a FunctionContext as a compact, evidence-backed Mermaid flowchart.

Built only from card facts (design/12 §Mermaid): solid edges are explicit
behaviour (guards, state changes, calls), dashed edges are implicit Frappe
lifecycle or external boundaries — visibly distinct, as the spec requires.
Deterministic (insertion-order ids) and capped at 20 nodes; nothing invented.
"""

from __future__ import annotations

from beagle.card.model import FunctionContext

_NODE_CAP = 20
_SHAPES = {
    "entry": ("([\"", "\"])"), "guard": ("{\"", "\"}"),
    "state": ("[\"", "\"]"), "call": ("[\"", "\"]"),
    "job": ("[[\"", "\"]]"), "boundary": ("[/\"", "\"/]"),
    "event": ("[(\"", "\")]"), "failure": ("[/\"", "\"/]"),
}


def _escape(label: str) -> str:
    return label.replace("\"", "'").replace("\n", " ")


class _Builder:
    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.nodes: list[str] = []
        self.edges: list[str] = []
        self.truncated = False

    def node(self, label: str, kind: str) -> str | None:
        if label in self.ids:
            return self.ids[label]
        if len(self.ids) >= _NODE_CAP:
            self.truncated = True
            return None
        nid = f"n{len(self.ids)}"
        self.ids[label] = nid
        open_s, close_s = _SHAPES[kind]
        self.nodes.append(f"    {nid}{open_s}{_escape(label)}{close_s}")
        return nid

    def edge(self, src: str, dst: str, arrow: str = "-->", label: str = "") -> None:
        tag = f"|{_escape(label)}|" if label else ""
        self.edges.append(f"    {src} {arrow}{tag} {dst}")

    def render(self) -> str:
        lines = ["flowchart TD", *self.nodes, *self.edges]
        if self.truncated:
            lines.append("    %% truncated: node cap reached")
        return "\n".join(lines)


def render(card: FunctionContext) -> str:
    b = _Builder()
    entry = b.node(_entry_label(card), "entry")
    cursor = _chain_guards(b, card, entry)
    cursor = _chain_effects(b, card, cursor)
    _add_dashed(b, card, cursor or entry)
    _add_failures(b, card, entry)
    if not b.nodes:
        b.node("(no behaviour extracted)", "state")
    return b.render()


def _entry_label(card: FunctionContext) -> str:
    if card.entrypoints:
        e = card.entrypoints[0]
        return f"{e.kind}: {e.detail}"
    return card.identity.qualified_name.rsplit(".", 1)[-1]


def _chain_guards(b: _Builder, card: FunctionContext, prev: str | None) -> str | None:
    for guard in card.guards:
        node = b.node(guard.text, "guard")
        if node is None:
            break
        if prev:
            b.edge(prev, node, "-->", "check")
        prev = node
    return prev


def _chain_effects(b: _Builder, card: FunctionContext, prev: str | None) -> str | None:
    for write in card.writes:
        node = b.node(f"{write.kind}: {write.target}", "state")
        if node and prev:
            b.edge(prev, node)
        prev = node or prev
    for call in card.calls:
        if call.category != "business":
            continue
        node = b.node(call.name, "call")
        if node and prev:
            b.edge(prev, node)
        prev = node or prev
    return prev


def _add_dashed(b: _Builder, card: FunctionContext, anchor: str | None) -> None:
    for path in card.lifecycle:
        label = f"{path.operation} {path.doctype} (lifecycle)"
        node = b.node(label, "event")
        if node and anchor:
            b.edge(anchor, node, "-.->")
    for job in card.jobs:
        node = b.node(f"enqueue {job.target}", "job")
        if node and anchor:
            b.edge(anchor, node, "-.->")
    for boundary in card.external_boundaries:
        node = b.node(boundary.detail, "boundary")
        if node and anchor:
            b.edge(anchor, node, "-.->")


def _add_failures(b: _Builder, card: FunctionContext, entry: str | None) -> None:
    for failure in card.failures:
        if failure.kind not in ("raises", "throws"):
            continue
        node = b.node(f"{failure.kind}: {failure.detail}", "failure")
        if node and entry:
            b.edge(entry, node, "-->", "fail")
