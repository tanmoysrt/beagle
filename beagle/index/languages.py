from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import tree_sitter
import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript

SCRIPT_BLOCK = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.DOTALL | re.IGNORECASE
)

PYTHON_QUERIES = {
    "definitions": """
        (function_definition name: (identifier) @name) @def
        (class_definition name: (identifier) @name) @def
    """,
    "imports": """
        (import_statement (dotted_name) @module)
        (import_from_statement module_name: (dotted_name) @module)
        (import_statement (aliased_import name: (dotted_name) @module alias: (identifier) @alias))
    """,
    "calls": """
        (call function: (identifier) @callee)
        (call function: (attribute attribute: (identifier) @callee))
    """,
}

TS_QUERIES = {
    "definitions": """
        (function_declaration name: (identifier) @name) @def
        (generator_function_declaration name: (identifier) @name) @def
        (class_declaration name: (_) @name) @def
        (interface_declaration name: (_) @name) @def
        (method_definition name: (_) @name) @def
        (variable_declarator name: (identifier) @name value: (arrow_function)) @def
        (variable_declarator name: (identifier) @name value: (function_expression)) @def
    """,
    "imports": """
        (import_statement source: (string) @module)
        (call_expression function: (import) arguments: (arguments (string) @module))
    """,
    "calls": """
        (call_expression function: (identifier) @callee)
        (call_expression function: (member_expression property: (property_identifier) @callee))
        (new_expression constructor: (identifier) @callee)
    """,
}

GO_QUERIES = {
    "definitions": """
        (function_declaration name: (identifier) @name) @def
        (method_declaration name: (field_identifier) @name) @def
        (type_declaration (type_spec name: (type_identifier) @name)) @def
    """,
    "imports": """
        (import_spec path: (interpreted_string_literal) @module)
    """,
    "calls": """
        (call_expression function: (identifier) @callee)
        (call_expression function: (selector_expression field: (field_identifier) @callee))
    """,
}

KIND_BY_NODE = {
    "function_definition": "function",
    "class_definition": "class",
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "method_definition": "method",
    "method_declaration": "method",
    "variable_declarator": "function",
    "type_declaration": "type",
}


@dataclass(frozen=True)
class Grammar:
    name: str
    language: tree_sitter.Language
    queries: dict[str, str]


@dataclass(frozen=True)
class SourceBlock:
    """A chunk of parseable source and where it starts in the original file."""

    grammar: Grammar
    source: bytes
    line_offset: int
    byte_offset: int


GRAMMAR_LOADERS = {
    "python": (tree_sitter_python.language, PYTHON_QUERIES),
    "typescript": (tree_sitter_typescript.language_typescript, TS_QUERIES),
    "tsx": (tree_sitter_typescript.language_tsx, TS_QUERIES),
    "javascript": (tree_sitter_javascript.language, TS_QUERIES),
    "go": (tree_sitter_go.language, GO_QUERIES),
}


@lru_cache(maxsize=None)
def grammar_for(name: str) -> Grammar | None:
    entry = GRAMMAR_LOADERS.get(name)
    if entry is None:
        return None
    loader, queries = entry
    return Grammar(name, tree_sitter.Language(loader()), queries)


@lru_cache(maxsize=None)
def compiled_query(grammar_name: str, kind: str) -> tree_sitter.Query | None:
    grammar = grammar_for(grammar_name)
    if grammar is None or kind not in grammar.queries:
        return None
    return tree_sitter.Query(grammar.language, grammar.queries[kind])


def parser_for(grammar: Grammar) -> tree_sitter.Parser:
    return tree_sitter.Parser(grammar.language)


def blocks_for(lang: str, source: bytes) -> list[SourceBlock]:
    """Parseable pieces of a file: normally one, but a Vue SFC has script blocks."""
    if lang == "vue":
        return vue_script_blocks(source)
    grammar = grammar_for(lang)
    return [SourceBlock(grammar, source, 0, 0)] if grammar else []


def vue_script_blocks(source: bytes) -> list[SourceBlock]:
    """Vue templates hold no call graph, so only the script blocks are parsed."""
    text = source.decode("utf-8", errors="replace")
    blocks = []
    for match in SCRIPT_BLOCK.finditer(text):
        is_ts = "ts" in match.group("attrs")
        grammar = grammar_for("typescript" if is_ts else "javascript")
        if grammar is None:
            continue
        body_start = match.start("body")
        blocks.append(
            SourceBlock(
                grammar,
                match.group("body").encode("utf-8"),
                line_offset=text.count("\n", 0, body_start),
                byte_offset=len(text[:body_start].encode("utf-8")),
            )
        )
    return blocks


def kind_of(node_type: str) -> str:
    return KIND_BY_NODE.get(node_type, "symbol")


def supported_languages() -> list[str]:
    return sorted(list(GRAMMAR_LOADERS) + ["vue"])
