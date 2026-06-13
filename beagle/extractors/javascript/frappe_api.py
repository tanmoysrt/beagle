"""Recognise frontend calls into the Frappe backend.

Pure functions over already-parsed call nodes. Given a call's function text and
its argument nodes, classify it as a backend *method* call or a *DocType* query
and pull out the string literal that names the target. Computed targets yield a
classification with a ``None`` target — the fact is kept, never guessed
(design/14).
"""

from __future__ import annotations

from typing import Optional

from beagle.extractors.javascript import binding

# Desk API: frappe.call({method}), frappe.xcall("dotted"), frappe.request.
_METHOD_CALLS = {"frappe.call", "frappe.xcall", "frappe.request"}
# frappe-ui helper: call("dotted", args).
_UI_CALL = {"call"}
# frappe-ui resource by url (a dotted method path or REST path).
_RESOURCE_URL = {"createResource"}
# frappe-ui resources that name a DocType.
_RESOURCE_DOCTYPE = {"createListResource", "createDocumentResource"}
_REST_METHOD_PREFIX = "/api/method/"


def detect(func_text: str, args: list[object], source: bytes) -> Optional[dict]:
    """Return a target descriptor for a backend call, or ``None``."""
    if func_text in _METHOD_CALLS:
        return _method(func_text, _method_target(args, source), len(args), False)
    if func_text in _UI_CALL:
        return _method(func_text, _first_string_arg(args, source), len(args), False)
    if func_text in _RESOURCE_URL:
        return _method(func_text, _resource_url(args, source), len(args), False)
    if func_text in _RESOURCE_DOCTYPE:
        return _doctype(func_text, _object_prop(args, "doctype", source), len(args))
    if func_text.startswith(("frappe.db.", "frappe.client.")):
        return _doctype(func_text, _first_string_arg(args, source), len(args))
    if func_text.endswith(".call"):  # frm.call / cur_frm.call / this.frm.call
        return _method(func_text, _method_target(args, source), len(args), True)
    return None


def _method(api: str, target: Optional[str], argc: int, controller_local: bool) -> dict:
    return {
        "api": api,
        "target_kind": "method",
        "method": target,
        "doctype": None,
        "controller_local": controller_local,
        "args": argc,
    }


def _doctype(api: str, target: Optional[str], argc: int) -> dict:
    return {
        "api": api,
        "target_kind": "doctype",
        "method": None,
        "doctype": target,
        "controller_local": False,
        "args": argc,
    }


def _method_target(args: list[object], source: bytes) -> Optional[str]:
    """A backend method: object ``{method: "..."}`` or a leading string arg."""
    from_object = _object_prop(args, "method", source)
    return from_object if from_object is not None else _first_string_arg(args, source)


def _resource_url(args: list[object], source: bytes) -> Optional[str]:
    url = _object_prop(args, "url", source)
    if url and url.startswith(_REST_METHOD_PREFIX):
        return url[len(_REST_METHOD_PREFIX):]
    return url


def _string_value(node: object, source: bytes) -> Optional[str]:
    if binding.kind(node) != "string":
        return None
    raw = binding.text(node, source)
    return raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'`" else raw


def _first_string_arg(args: list[object], source: bytes) -> Optional[str]:
    for arg in args:
        value = _string_value(arg, source)
        if value is not None:
            return value
    return None


def _object_prop(args: list[object], key: str, source: bytes) -> Optional[str]:
    for arg in args:
        if binding.kind(arg) != "object":
            continue
        for pair in binding.named_children(arg):
            if binding.kind(pair) != "pair":
                continue
            key_node = binding.field(pair, "key")
            if key_node is not None and binding.text(key_node, source) == key:
                return _string_value(binding.field(pair, "value"), source)
    return None
