"""Deterministic classification helpers for the context card.

Pure functions over already-extracted facts: detect external boundaries, rank
call importance, and derive a coarse action verb from a name. No I/O, no graph
access — so they are trivially testable and reusable by the Mermaid renderer.
"""

from __future__ import annotations

import re
from typing import Optional

_SUBPROCESS = {"subprocess.run", "subprocess.Popen", "subprocess.check_output",
               "subprocess.call", "subprocess.check_call", "os.system", "os.popen"}
_HTTP = {"requests.get", "requests.post", "requests.put", "requests.delete",
         "requests.patch", "requests.request", "urllib.request.urlopen"}
_SECURITY = {"frappe.has_permission", "frappe.only_for", "frappe.throw"}
_ENQUEUE = {"frappe.enqueue", "frappe.enqueue_doc"}
# A first-arg string is a shell command only with these markers, not any phrase.
_SHELL_HINT = re.compile(r"(?:^|\s)(?:--?\w|/\w|sudo |bash |sh |\w+/\w)")
# Trivial calls that add noise rather than understanding (design/12 low-value).
_TRIVIAL = {"len", "str", "int", "float", "list", "dict", "set", "tuple",
            "print", "repr", "format", "isinstance", "getattr", "setattr",
            "frappe.log_error", "frappe._", "_"}


def looks_like_shell_command(arg: str) -> bool:
    return bool(arg) and " " in arg and bool(_SHELL_HINT.search(arg))


def external_boundary(call: dict) -> Optional[tuple[str, str]]:
    """(kind, detail) when a call observation crosses an external boundary."""
    dotted = call.get("dotted")
    arg = call.get("first_arg") or ""
    if dotted in _SUBPROCESS:
        return ("shell", arg or call.get("func_code") or dotted)
    if dotted in _HTTP:
        return ("http", dotted + (f" {arg}" if arg else ""))
    if dotted is None and looks_like_shell_command(arg):
        return ("shell", arg)
    return None


def call_category(call: dict) -> Optional[str]:
    """Coarse importance category, or None for a low-value/trivial call."""
    dotted = call.get("dotted")
    if dotted in _ENQUEUE:
        return "job"
    if dotted in _SECURITY:
        return "security"
    if external_boundary(call):
        return "external"
    if dotted in _TRIVIAL or (call.get("attr") in _TRIVIAL):
        return None
    if call.get("super"):
        return None  # super() lifecycle continuation handled separately
    if call.get("head") in ("self", "cls") and call.get("attr"):
        return "business"
    # A bare local-function call (single name, no dotted receiver) is a business
    # call; dotted external/utility calls are left to the categories above or dropped.
    if dotted and "." not in dotted and dotted not in _TRIVIAL:
        return "business"
    return None


def action_verb(name: str) -> str:
    """First snake_case token as a coarse action (deactivate, retry, ...)."""
    token = name.lstrip("_").split("_", 1)[0]
    return token or name
