"""Stable identifier construction for Python entities.

IDs never include line numbers, so they survive edits that move code within a
file (design/03-data-model.md). Shape:

    module:   python://press.press.doctype.site.site
    class:    python://press.press.doctype.site.site#Site
    method:   python://press.press.doctype.site.site#Site.deploy
"""

from __future__ import annotations

import posixpath


def module_path_for(relpath: str) -> str:
    """Map a repo-relative ``.py`` path to a dotted module path."""
    normalized = relpath.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[: -len(".py")]
    if posixpath.basename(normalized) == "__init__":
        normalized = posixpath.dirname(normalized)
    return normalized.strip("/").replace("/", ".")


def module_id(module: str) -> str:
    return f"python://{module}"


def entity_id(module: str, qualified_name: str) -> str:
    return f"python://{module}#{qualified_name}"
