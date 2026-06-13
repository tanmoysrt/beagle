"""Stable identifiers and conventions for Frappe entities.

IDs follow design/03-data-model.md:

    doctype:        doctype://press/Site
    doctype field:  doctype-field://press/Site#status
    endpoint:       endpoint://press.api.deploy
    background job: job://press.tasks.poll
"""

from __future__ import annotations


def doctype_id(app: str, name: str) -> str:
    return f"doctype://{app}/{name}"


def field_id(app: str, name: str, fieldname: str) -> str:
    return f"doctype-field://{app}/{name}#{fieldname}"


def endpoint_id(dotted_path: str) -> str:
    return f"endpoint://{dotted_path}"


def job_id(dotted_path: str) -> str:
    return f"job://{dotted_path}"


def controller_class_name(doctype_name: str) -> str:
    """Frappe's controller class for a DocType drops spaces: ``Agent Job`` -> ``AgentJob``."""
    return doctype_name.replace(" ", "").replace("-", "")


def app_of(relpath: str) -> str:
    """The Frappe app a repo-relative path belongs to (its first segment)."""
    return relpath.replace("\\", "/").split("/", 1)[0]
