"""Small helpers for reading shapes out of LibCST expression nodes.

Pure functions over nodes; no traversal state. The extractor uses these to
describe call targets, base classes, and assignment values for the resolver.
"""

from __future__ import annotations

from typing import Optional

import libcst as cst


def dotted_name(node: cst.BaseExpression) -> Optional[str]:
    """Return ``a.b.c`` for a pure Name/Attribute chain, else ``None``."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        head = dotted_name(node.value)
        return f"{head}.{node.attr.value}" if head else None
    return None


def head_name(node: cst.BaseExpression) -> Optional[str]:
    """Return the leftmost Name of an attribute chain (``a`` in ``a.b.c``)."""
    while isinstance(node, cst.Attribute):
        node = node.value
    return node.value if isinstance(node, cst.Name) else None


def is_super_call(node: cst.BaseExpression) -> bool:
    """True for ``super()`` (the receiver of ``super().method()``)."""
    return (
        isinstance(node, cst.Call)
        and isinstance(node.func, cst.Name)
        and node.func.value == "super"
    )
