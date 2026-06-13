"""Filesystem discovery: repo-root detection, ignore rules, hashing.

Discovery decides *which* files exist and what changed. It never parses code.
Extraction layers consume the ``DiscoveredFile`` records it yields.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

import pathspec

from beagle.models import DiscoveredFile

# Files beagle is willing to look at. ``.py`` covers source, tests, and
# ``hooks.py``; ``.json`` carries Frappe DocType schema (used from stage 4).
_EXTENSIONS = {".py": "python", ".json": "json"}

# Always pruned, regardless of .gitignore.
_DEFAULT_IGNORES = [
    ".git/",
    ".hg/",
    ".svn/",
    ".beagle/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "node_modules/",
    "*.egg-info/",
    "dist/",
    "build/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
]


def find_repo_root(start: Path) -> Path:
    """Return the nearest ancestor containing ``.git`` (or ``start`` itself)."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_module(abspath: Path) -> str:
    """Derive a file's dotted module path by walking ``__init__.py`` boundaries.

    The module root is the first ancestor directory that is *not* a package, so
    multi-app layouts resolve correctly: ``apps/frappe/frappe`` is the
    ``frappe`` package, making ``.../frappe/model/document.py`` become
    ``frappe.model.document`` regardless of where indexing was rooted.
    """
    is_init = abspath.name == "__init__.py"
    names: list[str] = [] if is_init else [abspath.stem]
    cur = abspath.parent
    while (cur / "__init__.py").exists():
        names.insert(0, cur.name)
        cur = cur.parent
    return ".".join(names)


class Scanner:
    """Walks a root, honouring ignore rules, and yields indexable files."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._spec = self._load_spec()

    def _load_spec(self) -> pathspec.PathSpec:
        lines = list(_DEFAULT_IGNORES)
        gitignore = self.root / ".gitignore"
        if gitignore.is_file():
            lines += gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def _ignored(self, relpath: str, is_dir: bool) -> bool:
        probe = relpath + "/" if is_dir else relpath
        return self._spec.match_file(probe)

    def scan(self) -> Iterator[DiscoveredFile]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = os.path.relpath(dirpath, self.root)
            rel_dir = "" if rel_dir == "." else rel_dir
            # Prune ignored directories in place so os.walk skips them.
            dirnames[:] = [
                d
                for d in sorted(dirnames)
                if not self._ignored(os.path.join(rel_dir, d), is_dir=True)
            ]
            for name in sorted(filenames):
                language = _EXTENSIONS.get(Path(name).suffix)
                if language is None:
                    continue
                relpath = os.path.join(rel_dir, name) if rel_dir else name
                if self._ignored(relpath, is_dir=False):
                    continue
                discovered = self._describe(relpath, language)
                if discovered is not None:
                    yield discovered

    def _describe(self, relpath: str, language: str) -> DiscoveredFile | None:
        abspath = self.root / relpath
        try:
            data = abspath.read_bytes()
            stat = abspath.stat()
        except OSError:
            return None
        module = compute_module(abspath) if language == "python" else None
        return DiscoveredFile(
            relpath=relpath,
            abspath=str(abspath),
            language=language,
            hash=_hash_bytes(data),
            size=stat.st_size,
            mtime=stat.st_mtime,
            module=module,
        )
