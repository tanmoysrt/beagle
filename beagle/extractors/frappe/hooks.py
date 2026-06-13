"""Parse ``hooks.py`` runtime wiring.

Reads the module-level ``doc_events``, ``scheduler_events`` and
``override_doctype_class`` dictionaries and emits ``frappe_hook`` observations.
The resolver links them to DocTypes and handler functions. We never execute
hooks.py — it is parsed as text with LibCST, per the correctness rules.

Only literal string handlers are captured; computed handler paths are skipped
rather than guessed.
"""

from __future__ import annotations

from typing import Iterator

import libcst as cst

from beagle.extractors.python.naming import module_id
from beagle.models import Observation, SourceRange

_DOC_EVENTS = "doc_events"
_SCHEDULER = "scheduler_events"
_OVERRIDE_CLASS = "override_doctype_class"
_EXTEND_CLASS = "extend_doctype_class"
_OVERRIDE_METHODS = "override_whitelisted_methods"
_HAS_PERMISSION = "has_permission"
_PERMISSION_QUERY = "permission_query_conditions"


def is_hooks_file(relpath: str) -> bool:
    return relpath.replace("\\", "/").rsplit("/", 1)[-1] == "hooks.py"


def extract_hooks(relpath: str, text: str, module: str | None) -> list[Observation]:
    try:
        tree = cst.parse_module(text)
    except cst.ParserSyntaxError:
        return []
    subject = module_id(module or "")
    out: list[Observation] = []
    for name, value in _top_level_assignments(tree):
        if not isinstance(value, cst.Dict):
            continue
        if name == _DOC_EVENTS:
            out += _doc_events(relpath, subject, value)
        elif name == _SCHEDULER:
            out += _scheduler_events(relpath, subject, value)
        elif name == _OVERRIDE_CLASS:
            out += _override_class(relpath, subject, value)
        elif name == _EXTEND_CLASS:
            out += _extend_class(relpath, subject, value)
        elif name == _OVERRIDE_METHODS:
            out += _override_methods(relpath, subject, value)
        elif name == _HAS_PERMISSION:
            out += _permission(relpath, subject, value, "has_permission")
        elif name == _PERMISSION_QUERY:
            out += _permission(relpath, subject, value, "query_condition")
    return out


def _top_level_assignments(tree: cst.Module) -> Iterator[tuple[str, cst.BaseExpression]]:
    for stmt in tree.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if isinstance(small, cst.Assign) and len(small.targets) == 1:
                target = small.targets[0].target
                if isinstance(target, cst.Name):
                    yield target.value, small.value


def _string(node: cst.BaseExpression) -> str | None:
    if not isinstance(node, cst.SimpleString):
        return None
    value = node.evaluated_value
    return value if isinstance(value, str) else None


def _string_list(node: cst.BaseExpression) -> list[str]:
    """Strings from a single string, or a List/Tuple of strings."""
    single = _string(node)
    if single is not None:
        return [single]
    if isinstance(node, (cst.List, cst.Tuple)):
        return [s for e in node.elements if (s := _string(e.value)) is not None]
    return []


def _obs(relpath: str, subject: str, data: dict) -> Observation:
    return Observation(
        kind="frappe_hook",
        owner_file=relpath,
        subject=subject,
        source_range=SourceRange(1, 0, 1, 0),
        data=data,
    )


def _doc_events(relpath, subject, node: cst.Dict) -> list[Observation]:
    out: list[Observation] = []
    for doctype, events in _dict_items(node):
        if not isinstance(events, cst.Dict):
            continue
        for event, handlers in _dict_items(events):
            event_name = _string(event)
            for handler in _string_list(handlers):
                out.append(_obs(relpath, subject, {
                    "hook": "doc_event", "doctype": _string(doctype),
                    "event": event_name, "handler": handler,
                }))
    return out


def _scheduler_events(relpath, subject, node: cst.Dict) -> list[Observation]:
    out: list[Observation] = []
    for frequency, handlers in _dict_items(node):
        freq = _string(frequency)
        targets = _string_list(handlers)
        if isinstance(handlers, cst.Dict):  # cron: {expr: [handlers]}
            targets = [h for _, v in _dict_items(handlers) for h in _string_list(v)]
        for handler in targets:
            out.append(_obs(relpath, subject, {
                "hook": "scheduler", "frequency": freq, "handler": handler,
            }))
    return out


def _override_class(relpath, subject, node: cst.Dict) -> list[Observation]:
    out: list[Observation] = []
    for doctype, klass in _dict_items(node):
        handler = _string(klass)
        if handler:
            out.append(_obs(relpath, subject, {
                "hook": "override_class", "doctype": _string(doctype), "handler": handler,
            }))
    return out


def _extend_class(relpath, subject, node: cst.Dict) -> list[Observation]:
    out: list[Observation] = []
    for doctype, klass in _dict_items(node):
        for handler in _string_list(klass):
            out.append(_obs(relpath, subject, {
                "hook": "extend_class", "doctype": _string(doctype), "handler": handler,
            }))
    return out


def _override_methods(relpath, subject, node: cst.Dict) -> list[Observation]:
    out: list[Observation] = []
    for original, override in _dict_items(node):
        for handler in _string_list(override):
            out.append(_obs(relpath, subject, {
                "hook": "override_method", "original": _string(original), "handler": handler,
            }))
    return out


def _permission(relpath, subject, node: cst.Dict, ptype: str) -> list[Observation]:
    out: list[Observation] = []
    for doctype, handler in _dict_items(node):
        for path in _string_list(handler):
            out.append(_obs(relpath, subject, {
                "hook": "permission", "ptype": ptype,
                "doctype": _string(doctype), "handler": path,
            }))
    return out


def _dict_items(node: cst.Dict) -> Iterator[tuple[cst.BaseExpression, cst.BaseExpression]]:
    for element in node.elements:
        if isinstance(element, cst.DictElement):
            yield element.key, element.value
