"""Build dependency snapshots for a revision (design/15 §11).

Reads the revision's manifests directly from the mirror (no checkout), preferring
lockfiles over loose manifests, and stores the resulting pinned snapshot. Reading
is static — no manifest or package code is executed.
"""

from __future__ import annotations

from dataclasses import dataclass

from beagle.service.db import Database
from beagle.service.dependencies import ParsedPackage
from beagle.service.dependencies.js_manifests import parse_package_json, parse_package_lock
from beagle.service.dependencies.python_manifests import (
    parse_poetry_lock,
    parse_pylock,
    parse_requirements,
    parse_uv_lock,
)
from beagle.service.dependency_store import DependencyStore
from beagle.service.errors import NotFound
from beagle.service.git.mirror import GitMirror

# Ordered preference: the first present source per ecosystem wins (lockfiles first).
_PYTHON_SOURCES = [
    ("uv.lock", parse_uv_lock),
    ("poetry.lock", parse_poetry_lock),
    ("pylock.toml", parse_pylock),
    ("requirements.txt", parse_requirements),
]
_JS_SOURCES = [
    ("package-lock.json", parse_package_lock),
    ("package.json", parse_package_json),
]


@dataclass
class DependencyResult:
    snapshot_id: str
    commit_sha: str
    sources: list[str]
    package_count: int


class DependencyService:
    """Detects, parses, and stores dependency snapshots for revisions."""

    def __init__(self, database: Database, mirror: GitMirror, store: DependencyStore):
        self._db = database
        self._mirror = mirror
        self._store = store

    def analyze_revision(
        self, repository_id: str, revision: str, profile: str = "default"
    ) -> DependencyResult:
        sha = self._mirror.resolve(repository_id, revision)
        if not sha:
            raise NotFound(f"revision not found: {revision}")
        packages: list[ParsedPackage] = []
        sources: list[str] = []
        for candidates in (_PYTHON_SOURCES, _JS_SOURCES):
            chosen = self._first_present(repository_id, sha, candidates)
            if chosen:
                source_name, parsed = chosen
                sources.append(source_name)
                packages.extend(parsed)
        with self._db.connect() as conn:
            snapshot_id = self._store.replace_snapshot(
                conn, repository_id, sha, profile, sources, packages
            )
        return DependencyResult(snapshot_id, sha, sources, len(packages))

    def _first_present(self, repository_id: str, sha: str, candidates):
        for filename, parser in candidates:
            raw = self._mirror.read_file(repository_id, sha, filename)
            if raw is None:
                continue
            try:
                return filename, parser(raw.decode("utf-8", errors="replace"))
            except Exception:
                continue
        return None
