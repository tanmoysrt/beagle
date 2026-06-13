"""Render an investigation's structured result as a compact Mermaid flowchart.

Built only from indexed evidence (design/11 §15): solid edges are explicit
calls, dashed edges are implicit framework lifecycle or external boundaries
(visibly distinct, as the spec requires). Output is deterministic — node ids
follow insertion order — and capped at 20 nodes.
"""

from __future__ import annotations

_NODE_CAP = 20
_CALL = ("[\"", "\"]")
_DECISION = ("{\"", "\"}")
_DOCTYPE = ("[(\"", "\")]")
_BOUNDARY = ("[/\"", "\"/]")


def _escape(label: str) -> str:
    return label.replace("\"", "'").replace("\n", " ")


class _Builder:
    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.node_lines: list[str] = []
        self.edge_lines: list[str] = []
        self.truncated = False

    def full(self) -> bool:
        return len(self.ids) >= _NODE_CAP

    def node(self, label: str, shape=_CALL) -> str | None:
        if label in self.ids:
            return self.ids[label]
        if self.full():
            self.truncated = True
            return None
        nid = f"n{len(self.ids)}"
        self.ids[label] = nid
        self.node_lines.append(f"    {nid}{shape[0]}{_escape(label)}{shape[1]}")
        return nid

    def edge(self, src: str, dst: str, arrow: str = "-->", label: str = "") -> None:
        tag = f"|{_escape(label)}|" if label else ""
        self.edge_lines.append(f"    {src} {arrow}{tag} {dst}")

    def render(self) -> str:
        lines = ["flowchart TD", *self.node_lines, *self.edge_lines]
        if self.truncated:
            lines.append("    %% truncated: node cap reached")
        return "\n".join(lines)


def _add_chain(b: _Builder, data: dict) -> None:
    workflows = data.get("primary_workflows") or []
    steps = workflows[0]["steps"] if workflows else []
    prev = None
    for step in steps:
        cur = b.node(step)
        if cur is None:
            break
        if prev:
            b.edge(prev, cur)
        prev = cur


def _add_conditions(b: _Builder, data: dict) -> None:
    for cond in data.get("conditions", []):
        where = b.ids.get(cond["where"])
        node = b.node(cond["text"], _DECISION)
        if where and node:
            b.edge(where, node, "-->", "checks")


def _add_framework(b: _Builder, data: dict) -> None:
    for fw in data.get("framework_events", []):
        caller = b.ids.get(fw.get("caller_name", ""))
        label = f"{fw['operation']} {fw['doctype']} (lifecycle)"
        node = b.node(label, _DOCTYPE)
        if caller and node:
            b.edge(caller, node, "-.->")


def _add_boundaries(b: _Builder, data: dict) -> None:
    for boundary in data.get("external_boundaries", []):
        where = b.ids.get(boundary["where"])
        node = b.node(boundary["command"], _BOUNDARY)
        if where and node:
            b.edge(where, node, "-.->")


def render(data: dict) -> str:
    b = _Builder()
    _add_chain(b, data)
    _add_conditions(b, data)
    _add_framework(b, data)
    _add_boundaries(b, data)
    if not b.node_lines:
        b.node("(no workflow reconstructed)")
    return b.render()
