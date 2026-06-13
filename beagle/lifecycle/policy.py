"""Versioned, source-backed Frappe document lifecycle policy.

Event orderings are taken from the pinned Frappe source (NOT the docs table):
``frappe/model/document.py`` at the commit in ``POLICY_META``. Verified
functions: ``insert``, ``_save``, ``run_before_save_methods``,
``run_post_save_methods``, ``submit``/``_submit``, ``cancel``/``_cancel``,
``db_set``, ``discard``; delete via ``frappe/model/delete_doc.py``.

The adapter is intentionally small (design/10): one policy for the pinned
source. Add another adapter only when a supported Frappe version differs — never
silently mutate these sequences.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

POLICY_META = {
    "framework": "frappe",
    "version": "16.0.0-dev",
    "commit": "12c3503ac098e1cfca1875b29dbc43347c27e84b",
    "policy_version": 1,
}

# Categories: "event" (a run_method dispatch), "validation", "persist" (DB write).
_EVENT, _VALIDATION, _PERSIST = "event", "validation", "persist"


@dataclass(frozen=True)
class LifecycleEvent:
    name: str
    order: int
    category: str
    conditional: bool = False
    note: str = ""


# (name, category, conditional, note) per operation relationship.
# `conditional` marks steps a statically-visible flag can suppress.
_SEQUENCES: dict[str, list[tuple[str, str, bool, str]]] = {
    "INSERTS_DOCTYPE": [
        ("before_insert", _EVENT, False, ""),
        ("before_validate", _EVENT, False, ""),
        ("validate", _EVENT, True, "skipped if ignore_validate"),
        ("before_save", _EVENT, True, "skipped if ignore_validate"),
        ("db_insert", _PERSIST, False, ""),
        ("after_insert", _EVENT, False, ""),
        ("on_update", _EVENT, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "SAVES_DOCTYPE": [
        ("before_validate", _EVENT, False, ""),
        ("validate", _EVENT, True, "skipped if ignore_validate"),
        ("before_save", _EVENT, True, "skipped if ignore_validate"),
        ("db_update", _PERSIST, False, ""),
        ("on_update", _EVENT, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "SUBMITS_DOCTYPE": [
        ("before_validate", _EVENT, False, ""),
        ("validate", _EVENT, True, "skipped if ignore_validate"),
        ("before_submit", _EVENT, True, "skipped if ignore_validate"),
        ("db_update", _PERSIST, False, ""),
        ("on_update", _EVENT, False, ""),
        ("on_submit", _EVENT, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "CANCELS_DOCTYPE": [
        ("before_cancel", _EVENT, False, "no before_validate/validate on cancel"),
        ("db_update", _PERSIST, False, ""),
        ("on_cancel", _EVENT, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "UPDATES_AFTER_SUBMIT": [
        ("before_update_after_submit", _EVENT, False, ""),
        ("validate_update_after_submit", _VALIDATION, False, ""),
        ("db_update", _PERSIST, False, ""),
        ("on_update_after_submit", _EVENT, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "DB_SETS_DOCTYPE": [
        ("before_change", _EVENT, False, "db_set does not run validate/save lifecycle"),
        ("db_update_field", _PERSIST, False, ""),
        ("on_change", _EVENT, False, ""),
    ],
    "DELETES_DOCTYPE": [
        ("on_trash", _EVENT, True, "skipped if ignore_on_trash"),
        ("on_change", _EVENT, False, ""),
        ("db_delete", _PERSIST, False, ""),
        ("after_delete", _EVENT, False, ""),
    ],
    "DISCARDS_DOCTYPE": [
        ("before_discard", _EVENT, False, ""),
        ("before_change", _EVENT, False, "nested db_set(docstatus)"),
        ("db_update_field", _PERSIST, False, "nested db_set(docstatus)"),
        ("on_change", _EVENT, False, "nested db_set(docstatus)"),
        ("on_discard", _EVENT, False, ""),
    ],
}


class LifecyclePolicy(ABC):
    @abstractmethod
    def events_for(self, relationship: str) -> list[LifecycleEvent]: ...

    @abstractmethod
    def supports(self, framework_version: str) -> bool: ...


class FrappeLifecyclePolicy(LifecyclePolicy):
    meta = POLICY_META

    def events_for(self, relationship: str) -> list[LifecycleEvent]:
        spec = _SEQUENCES.get(relationship, [])
        return [
            LifecycleEvent(name=n, order=i, category=c, conditional=cond, note=note)
            for i, (n, c, cond, note) in enumerate(spec)
        ]

    def supports(self, framework_version: str) -> bool:
        return framework_version.split(".", 1)[0] in ("15", "16")

    @property
    def dispatch_events(self) -> set[str]:
        """Events that dispatch to controller methods and doc_events handlers."""
        return {
            "before_insert", "before_validate", "validate", "before_save",
            "before_submit", "before_cancel", "before_update_after_submit",
            "after_insert", "on_update", "on_submit", "on_cancel",
            "on_update_after_submit", "on_change", "before_change", "on_trash",
            "after_delete", "before_discard", "on_discard",
        }
