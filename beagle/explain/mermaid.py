"""Render a FlowGraph as a deterministic Mermaid flowchart.

Node shape encodes kind; uncertain edges are dashed (design/08: "mark uncertain
edges"). Output ordering follows node/edge insertion order, so the same input
always yields byte-identical Mermaid.
"""

from __future__ import annotations

from beagle.explain.flow import FlowGraph

_SHAPES = {
    "branch": ("{\"", "\"}"),
    "raise": ("[/\"", "\"/]"),
    "except": ("[/\"", "\"/]"),
    "return": ("([\"", "\"])"),
    "entry": ("([\"", "\"])"),
    "doctype": ("[(\"", "\")]"),
    "job": ("[[\"", "\"]]"),
}
_DEFAULT_SHAPE = ("[\"", "\"]")


def _escape(label: str) -> str:
    return label.replace("\"", "'")


def render(graph: FlowGraph) -> str:
    lines = ["flowchart TD"]
    for node in graph.nodes:
        open_s, close_s = _SHAPES.get(node.kind, _DEFAULT_SHAPE)
        lines.append(f"    {node.id}{open_s}{_escape(node.label)}{close_s}")
    for edge in graph.edges:
        arrow = "-.->" if edge.uncertain else "-->"
        label = f"|{_escape(edge.label)}|" if edge.label else ""
        lines.append(f"    {edge.src} {arrow}{label} {edge.dst}")
    if graph.truncated:
        lines.append("    %% truncated: node cap reached")
    return "\n".join(lines)
