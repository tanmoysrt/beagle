"""Cache and index downloaded dependency artifacts (design/15 §12, §14).

A downloaded artifact is unpacked safely (no scripts, archive guards) and indexed
once with the existing engine into a self-contained snapshot. The cache is keyed
by artifact hash so a public package is fetched and indexed a single time and
reused across repositories. Compiled extensions are never loaded — only source
and stubs are indexed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from beagle.service.config import ServiceConfig
from beagle.service.dependencies.registry import DownloadedArtifact
from beagle.service.dependencies.safe_acquire import safe_extract_tar, safe_extract_zip
from beagle.workspace import Workspace

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._@-]")


@dataclass
class CachedArtifact:
    ecosystem: str
    name: str
    version: str
    hash: str
    source_dir: str
    index_path: str
    module_count: int


class ArtifactCache:
    """Stores unpacked + indexed artifacts under the storage root, keyed by hash."""

    def __init__(self, config: ServiceConfig):
        self._root = config.repo_storage_root / "artifacts"

    def acquire(self, artifact: DownloadedArtifact) -> CachedArtifact:
        target = self._dir_for(artifact)
        index_path = target / "index.db"
        source_dir = target / "src"
        if index_path.exists():
            return self._load(artifact, source_dir, index_path)
        source_dir.mkdir(parents=True, exist_ok=True)
        self._unpack(artifact, source_dir)
        module_count = self._index(source_dir, index_path)
        return CachedArtifact(
            artifact.ecosystem, artifact.name, artifact.version, artifact.hash,
            str(source_dir), str(index_path), module_count,
        )

    def _unpack(self, artifact: DownloadedArtifact, dest: Path) -> None:
        if artifact.kind == "wheel":
            safe_extract_zip(artifact.data, dest)
        else:
            safe_extract_tar(artifact.data, dest)

    def _index(self, source_dir: Path, index_path: Path) -> int:
        workspace = Workspace(source_dir, db_path=index_path)
        try:
            workspace.index(force=True)
            modules = [e for e in workspace.repo.iter_entities() if e.kind == "module"]
            return len(modules)
        finally:
            workspace.close()

    def _load(
        self, artifact: DownloadedArtifact, source_dir: Path, index_path: Path
    ) -> CachedArtifact:
        from beagle.database import Database as EngineDatabase
        from beagle.database.repository import Repository as EngineRepository

        database = EngineDatabase(index_path)
        try:
            modules = [e for e in EngineRepository(database).iter_entities() if e.kind == "module"]
            count = len(modules)
        finally:
            database.close()
        return CachedArtifact(
            artifact.ecosystem, artifact.name, artifact.version, artifact.hash,
            str(source_dir), str(index_path), count,
        )

    def _dir_for(self, artifact: DownloadedArtifact) -> Path:
        digest = _SAFE_KEY.sub("_", artifact.hash)[:32]
        safe_name = _SAFE_KEY.sub("_", artifact.name)
        return self._root / artifact.ecosystem / safe_name / f"{artifact.version}-{digest}"
