"""Vue single-file component handling.

A ``.vue`` file is HTML-ish: the logic lives in one or more ``<script>`` blocks.
We locate each block with the Vue grammar, then parse its raw body with the
JS/TS extractor, preserving line numbers via an offset so every entity and call
reports a range in the ``.vue`` file's own coordinates (design/14).
"""

from __future__ import annotations

from typing import Optional

from beagle.extractors.javascript import binding
from beagle.extractors.javascript.extractor import JsExtraction, extract_javascript
from beagle.extractors.javascript.naming import module_id, normalize_relpath
from beagle.models import Entity


def extract_vue(relpath: str, text: str) -> JsExtraction:
    tree = binding.parse("vue", text)
    out = JsExtraction()
    if tree is None:
        return out
    out.entities.append(_module_entity(relpath, tree.root))
    for code, offset, language in _script_blocks(tree.root, tree.source):
        sub = extract_javascript(relpath, code, language, line_offset=offset)
        out.entities += [e for e in sub.entities if e.kind != "js_module"]
        out.observations += sub.observations
        out.chunks += sub.chunks
    return out


def _module_entity(relpath: str, root: object) -> Entity:
    normalized = normalize_relpath(relpath)
    return Entity(
        id=module_id(normalized),
        kind="js_module",
        name=normalized.rsplit("/", 1)[-1],
        qualified_name=normalized,
        owner_file=normalized,
        source_range=binding.source_range(root),
    )


def _script_blocks(root: object, source: bytes) -> list[tuple[str, int, str]]:
    blocks: list[tuple[str, int, str]] = []
    for node in binding.walk(root):
        if binding.kind(node) != "script_element":
            continue
        raw = _raw_text(node)
        if raw is None:
            continue
        offset = raw.start_position().row
        blocks.append((binding.text(raw, source), offset, _script_language(node, source)))
    return blocks


def _raw_text(script_element: object) -> Optional[object]:
    for child in binding.named_children(script_element):
        if binding.kind(child) == "raw_text":
            return child
    return None


def _script_language(script_element: object, source: bytes) -> str:
    for child in binding.named_children(script_element):
        if binding.kind(child) != "start_tag":
            continue
        for attr in binding.named_children(child):
            if binding.kind(attr) != "attribute":
                continue
            text = binding.text(attr, source).lower()
            if "lang" in text and ("ts" in text or "typescript" in text):
                return "typescript"
    return "javascript"
