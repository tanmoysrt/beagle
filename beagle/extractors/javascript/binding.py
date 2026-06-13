"""Thin adapter over the bundled tree-sitter binding.

The ``tree-sitter-language-pack`` wheel exposes a Rust-backed binding whose API
differs from upstream py-tree-sitter: node *type* is ``kind``, several accessors
(``root_node``, ``start_position``, ``byte_range``, ``named_child``) are methods
rather than properties, and nodes carry no ``.text``. Every one of those quirks
is contained here, so the extractor sees a small, stable node interface and a
binding swap touches only this file.

Parsing is text-only; it never imports or executes the source under analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from tree_sitter_language_pack import get_parser

from beagle.models import SourceRange

_PARSERS: dict[str, object] = {}

# beagle language label -> tree-sitter grammar name.
_GRAMMAR = {"javascript": "javascript", "typescript": "typescript", "vue": "vue"}


@dataclass(frozen=True)
class Tree:
    """A parsed source: the grammar root plus the bytes it was parsed from.

    Bytes are kept because the binding reports positions as UTF-8 byte offsets
    and nodes cannot return their own text.
    """

    root: object
    source: bytes


def parse(language: str, text: str) -> Optional[Tree]:
    grammar = _GRAMMAR.get(language)
    if grammar is None:
        return None
    parser = _PARSERS.get(grammar)
    if parser is None:
        parser = get_parser(grammar)
        _PARSERS[grammar] = parser
    tree = parser.parse(text)
    return Tree(root=tree.root_node(), source=text.encode("utf-8"))


def kind(node: object) -> str:
    return node.kind()


def text(node: object, source: bytes) -> str:
    rng = node.byte_range()
    return source[rng.start : rng.end].decode("utf-8", errors="replace")


def source_range(node: object) -> SourceRange:
    start = node.start_position()
    end = node.end_position()
    return SourceRange(start.row + 1, start.column, end.row + 1, end.column)


def field(node: object, name: str) -> Optional[object]:
    return node.child_by_field_name(name)


def named_children(node: object) -> list[object]:
    return [node.named_child(i) for i in range(node.named_child_count())]


def walk(node: object) -> Iterator[object]:
    """Yield ``node`` and every named descendant, depth-first."""
    yield node
    for child in named_children(node):
        yield from walk(child)
