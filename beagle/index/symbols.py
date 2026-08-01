from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter

from .languages import SourceBlock, blocks_for, compiled_query, kind_of, parser_for

MAX_SIGNATURE_CHARS = 200


@dataclass
class Symbol:
    name: str
    qualified_name: str
    kind: str
    lang: str
    signature: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    parent: "Symbol | None" = None

    def contains(self, byte_offset: int) -> bool:
        return self.start_byte <= byte_offset < self.end_byte


@dataclass
class Reference:
    """A call or name use, attached to the symbol it appears inside."""

    name: str
    line: int
    byte_offset: int
    source_symbol: Symbol | None = None


@dataclass
class ImportRecord:
    module: str
    symbol: str | None = None
    alias: str | None = None
    line: int = 0


@dataclass
class ParsedFile:
    path: str
    lang: str
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)


class SymbolExtractor:
    """Pulls definitions, imports and call sites out of one file."""

    def parse(self, path: str, lang: str, source: bytes) -> ParsedFile:
        parsed = ParsedFile(path=path, lang=lang)
        for block in blocks_for(lang, source):
            self.parse_block(parsed, block)
        return parsed

    def parse_block(self, parsed: ParsedFile, block: SourceBlock) -> None:
        tree = parser_for(block.grammar).parse(block.source)
        symbols = self.extract_symbols(block, tree)
        parsed.symbols.extend(symbols)
        parsed.imports.extend(self.extract_imports(block, tree))
        parsed.references.extend(self.extract_references(block, tree, symbols))

    def extract_symbols(self, block: SourceBlock, tree: tree_sitter.Tree) -> list[Symbol]:
        query = compiled_query(block.grammar.name, "definitions")
        if query is None:
            return []
        found = []
        for _, captures in tree_sitter.QueryCursor(query).matches(tree.root_node):
            definition = first(captures.get("def"))
            name_node = first(captures.get("name"))
            if definition is None or name_node is None:
                continue
            found.append(self.build_symbol(block, definition, name_node))
        found.sort(key=lambda symbol: (symbol.start_byte, -symbol.end_byte))
        assign_parents(found)
        return found

    def build_symbol(
        self, block: SourceBlock, definition: tree_sitter.Node, name_node: tree_sitter.Node
    ) -> Symbol:
        name = node_text(block.source, name_node)
        return Symbol(
            name=name,
            qualified_name=name,
            kind=kind_of(definition.type),
            lang=block.grammar.name,
            signature=signature_of(block.source, definition),
            start_line=definition.start_point[0] + block.line_offset + 1,
            end_line=definition.end_point[0] + block.line_offset + 1,
            start_byte=definition.start_byte + block.byte_offset,
            end_byte=definition.end_byte + block.byte_offset,
        )

    def extract_imports(self, block: SourceBlock, tree: tree_sitter.Tree) -> list[ImportRecord]:
        query = compiled_query(block.grammar.name, "imports")
        if query is None:
            return []
        records = []
        for _, captures in tree_sitter.QueryCursor(query).matches(tree.root_node):
            module_node = first(captures.get("module"))
            if module_node is None:
                continue
            alias_node = first(captures.get("alias"))
            records.append(
                ImportRecord(
                    module=node_text(block.source, module_node).strip("\"'`"),
                    alias=node_text(block.source, alias_node) if alias_node else None,
                    line=module_node.start_point[0] + block.line_offset + 1,
                )
            )
        return records

    def extract_references(
        self, block: SourceBlock, tree: tree_sitter.Tree, symbols: list[Symbol]
    ) -> list[Reference]:
        query = compiled_query(block.grammar.name, "calls")
        if query is None:
            return []
        references = []
        for _, captures in tree_sitter.QueryCursor(query).matches(tree.root_node):
            callee = first(captures.get("callee"))
            if callee is None:
                continue
            offset = callee.start_byte + block.byte_offset
            references.append(
                Reference(
                    name=node_text(block.source, callee),
                    line=callee.start_point[0] + block.line_offset + 1,
                    byte_offset=offset,
                    source_symbol=innermost_containing(symbols, offset),
                )
            )
        return references


def assign_parents(symbols: list[Symbol]) -> None:
    """Nest symbols by containment and build dotted qualified names."""
    stack: list[Symbol] = []
    for symbol in symbols:
        while stack and not stack[-1].contains(symbol.start_byte):
            stack.pop()
        if stack:
            symbol.parent = stack[-1]
            symbol.qualified_name = f"{stack[-1].qualified_name}.{symbol.name}"
        stack.append(symbol)


def innermost_containing(symbols: list[Symbol], byte_offset: int) -> Symbol | None:
    best = None
    for symbol in symbols:
        if symbol.contains(byte_offset):
            if best is None or symbol.start_byte >= best.start_byte:
                best = symbol
    return best


def signature_of(source: bytes, definition: tree_sitter.Node) -> str:
    body = definition.child_by_field_name("body")
    end = body.start_byte if body else definition.end_byte
    text = source[definition.start_byte : end].decode("utf-8", errors="replace")
    text = " ".join(text.split())
    return text[:MAX_SIGNATURE_CHARS]


def node_text(source: bytes, node: tree_sitter.Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def first(nodes: list[tree_sitter.Node] | None) -> tree_sitter.Node | None:
    return nodes[0] if nodes else None
