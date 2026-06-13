"""Render a lifecycle TraceGraph as Mermaid (design/09 edge conventions).

Edge categories are visibly distinct:
- solid  ``-->``           explicit Python call / document operation
- dashed ``-.->|lifecycle|`` framework lifecycle dispatch
- dashed ``-.->|runtime?|``  possible runtime-configured dispatch (uncertain)

Handler categories appear as their own nodes rather than as direct calls from
the original function.
"""

from __future__ import annotations

from beagle.lifecycle.service import TraceGraph

_NODE_SHAPE = {
    "function": ("[\"", "\"]"),
    "doctype": ("[(\"", "\")]"),
    "event": ("{\"", "\"}"),
    "controller": ("[\"", "\"]"),
    "exact_doc_event": ("[\"", "\"]"),
    "wildcard_doc_event": ("[\"", "\"]"),
    "runtime": ("[/\"", "\"/]"),
}
_EDGE = {
    "operation": "-->",
    "framework": "-.->|lifecycle|",
    "runtime": "-.->|runtime?|",
    "call": "-->",
}


def _escape(text: str) -> str:
    return text.replace("\"", "'")


def render(graph: TraceGraph) -> str:
    ids = {node_id: f"n{i}" for i, node_id in enumerate(graph.nodes)}
    lines = ["flowchart TD"]
    for node_id, (label, kind) in graph.nodes.items():
        open_s, close_s = _NODE_SHAPE.get(kind, ("[\"", "\"]"))
        lines.append(f"    {ids[node_id]}{open_s}{_escape(label)}{close_s}")
    for src, dst, category in graph.edges:
        if src in ids and dst in ids:
            lines.append(f"    {ids[src]} {_EDGE.get(category, '-->')} {ids[dst]}")
    if graph.truncated:
        lines.append("    %% truncated: trace node cap reached")
    return "\n".join(lines)
