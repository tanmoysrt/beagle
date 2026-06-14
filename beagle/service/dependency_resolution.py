"""Download dependency source and resolve project imports across packages.

Orchestrates the network-bound slice of design/15 §11–§13: for a revision's
dependency snapshot, download each artifact, index it (cached by hash), and
resolve the project's imports to the exact dependency version that provides them.
Downloads are injected so tests can use a local fixture registry; nothing is
executed during indexing.

Cross-package *symbol* resolution is implemented for Python (the design's
press→frappe example). JavaScript artifacts are still downloaded, verified, and
indexed; resolving JS symbol edges across packages remains a follow-up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from beagle.service import ids
from beagle.service.clock import now_iso
from beagle.service.db import Database
from beagle.service.dependencies.artifact_cache import ArtifactCache
from beagle.service.dependencies.cross_resolve import (
    CrossPackageResolver,
    Resolution,
    load_artifact_modules,
)
from beagle.service.dependencies.registry import NpmRegistry, PythonRegistry
from beagle.service.dependency_store import DependencyStore
from beagle.service.errors import NotFound
from beagle.service.git.mirror import GitMirror
from beagle.service.revision_indexer import RevisionIndexer


@dataclass
class ResolutionSummary:
    repository_id: str
    commit_sha: str
    downloaded: int
    indexed_modules: int
    resolved: int
    unresolved: int


class DependencyResolutionService:
    """Acquires dependency source and resolves project imports against it."""

    def __init__(
        self, database: Database, mirror: GitMirror, dep_store: DependencyStore,
        cache: ArtifactCache, indexer: RevisionIndexer,
        python_registry: PythonRegistry | None = None,
        npm_registry: NpmRegistry | None = None,
    ):
        self._db = database
        self._mirror = mirror
        self._dep_store = dep_store
        self._cache = cache
        self._indexer = indexer
        self._python = python_registry or PythonRegistry()
        self._npm = npm_registry or NpmRegistry()

    def resolve_revision(
        self, repository_id: str, revision: str, max_packages: int = 200
    ) -> ResolutionSummary:
        sha = self._mirror.resolve(repository_id, revision)
        if not sha:
            raise NotFound(f"revision not found: {revision}")
        with self._db.connect() as conn:
            snapshot = self._dep_store.get_snapshot(conn, repository_id, sha)
        project_index = self._indexer.index_revision(repository_id, sha).artifact_path
        artifacts, downloaded, modules = self._acquire(snapshot["packages"][:max_packages])
        resolver = CrossPackageResolver(artifacts)
        resolutions = resolver.resolve_project(project_index)
        self._persist(repository_id, sha, resolutions)
        resolved = sum(1 for r in resolutions if r.resolved)
        return ResolutionSummary(
            repository_id, sha, downloaded, modules, resolved, len(resolutions) - resolved
        )

    def _acquire(self, packages: list[dict]):
        artifacts = []
        downloaded = 0
        module_total = 0
        for package in packages:
            cached = self._acquire_one(package)
            if not cached:
                continue
            downloaded += 1
            module_total += cached.module_count
            if package["ecosystem"] == "python":
                artifacts.append(
                    load_artifact_modules(
                        cached.name, cached.version, cached.hash, cached.index_path
                    )
                )
        return artifacts, downloaded, module_total

    def _acquire_one(self, package: dict):
        try:
            registry = self._python if package["ecosystem"] == "python" else self._npm
            artifact = registry.download(
                package["name"], package["version"], package.get("hash")
            )
            return self._cache.acquire(artifact)
        except Exception:
            return None  # a single bad/unavailable package must not fail the whole pass

    def _persist(self, repository_id: str, sha: str, resolutions: list[Resolution]) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM dependency_resolutions WHERE repository_id = ? AND commit_sha = ?",
                (repository_id, sha),
            )
            for resolution in resolutions:
                conn.execute(
                    "INSERT INTO dependency_resolutions(id, repository_id, commit_sha,"
                    " import_module, symbol, package, version, artifact_hash, resolved,"
                    " confidence, evidence, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ids._new("res"), repository_id, sha, resolution.import_module,
                     resolution.symbol, resolution.package, resolution.version,
                     resolution.artifact_hash, 1 if resolution.resolved else 0,
                     0.9 if resolution.resolved else 0.5, resolution.evidence, now_iso()),
                )

    def list_resolutions(
        self, conn, repository_id: str, commit_sha: str, limit: int = 200
    ) -> list[dict]:
        return conn.fetch_all(
            "SELECT import_module, symbol, package, version, artifact_hash, resolved,"
            " confidence, evidence FROM dependency_resolutions"
            " WHERE repository_id = ? AND commit_sha = ? ORDER BY package, import_module LIMIT ?",
            (repository_id, commit_sha, limit),
        )
