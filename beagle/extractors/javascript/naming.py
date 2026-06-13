"""Stable identifiers for JavaScript/TypeScript/Vue entities.

JS module identity is the file path (not a dotted module like Python), so ids
are path-based and carry a ``js://`` scheme. Ids never include line numbers, so
they survive edits that move code within a file (design/14).

    module:   js://app/public/js/site.js
    class:    js://app/public/js/site.js#SiteController
    method:   js://app/public/js/site.js#SiteController.refresh
"""

from __future__ import annotations

_PREFIX = "js://"


def normalize_relpath(relpath: str) -> str:
    return relpath.replace("\\", "/").strip("/")


def module_id(relpath: str) -> str:
    return f"{_PREFIX}{normalize_relpath(relpath)}"


def entity_id(relpath: str, qualified_name: str) -> str:
    return f"{_PREFIX}{normalize_relpath(relpath)}#{qualified_name}"
