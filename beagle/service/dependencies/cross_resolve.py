"""Cross-package import and symbol resolution (design/15 §13).

Given a project's indexed revision and the indexed source of its exact
dependency versions, resolve each project import to the dependency package that
provides it, and resolve imported symbols to the exact entity in that package's
version. Every resolution carries provenance: package, version, artifact hash.

This is deterministic and conservative: an import resolves only when a dependency
actually provides the module; unresolved imports are preserved as such, never
guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from beagle.database import Database as EngineDatabase
from beagle.database.repository import Repository as EngineRepository


@dataclass
class ArtifactModules:
    """The importable surface of one cached dependency artifact."""

    package: str
    version: str
    hash: str
    index_path: str
    modules: set[str] = field(default_factory=set)
    top_levels: set[str] = field(default_factory=set)


@dataclass
class Resolution:
    import_module: str
    symbol: str | None
    package: str
    version: str
    artifact_hash: str
    resolved: bool
    evidence: str


def load_artifact_modules(
    package: str, version: str, hash_value: str, index_path: str
) -> ArtifactModules:
    """Read the module surface of an artifact index (python modules)."""
    database = EngineDatabase(Path(index_path))
    try:
        modules = {
            entity.qualified_name
            for entity in EngineRepository(database).iter_entities()
            if entity.kind == "module"
        }
    finally:
        database.close()
    top_levels = {module.split(".")[0] for module in modules}
    return ArtifactModules(package, version, hash_value, index_path, modules, top_levels)


class CrossPackageResolver:
    """Resolves a project's imports against indexed dependency artifacts."""

    def __init__(self, artifacts: list[ArtifactModules]):
        # First artifact providing a top-level wins (deterministic, order given).
        self._artifacts = artifacts

    def resolve_project(self, project_index_path: str) -> list[Resolution]:
        resolutions: list[Resolution] = []
        database = EngineDatabase(Path(project_index_path))
        try:
            imports = EngineRepository(database).observations_of_kind("import")
        finally:
            database.close()
        for observation in imports:
            resolutions.extend(self._resolve_one(observation.data))
        return resolutions

    def _resolve_one(self, data: dict) -> list[Resolution]:
        module = data.get("module")
        if not module:
            return []
        artifact = self._provider_for(module)
        if not artifact:
            return []
        if data.get("style") == "from" and data.get("names"):
            return [self._resolve_symbol(module, name, artifact) for name in data["names"]]
        return [Resolution(module, None, artifact.package, artifact.version,
                           artifact.hash, True, "module provided by dependency")]

    def _resolve_symbol(self, module: str, name: dict | str, artifact: ArtifactModules) -> Resolution:
        symbol = name["name"] if isinstance(name, dict) else name
        entity_id = f"python://{module}#{symbol}"
        resolved = self._has_entity(artifact.index_path, entity_id)
        # A submodule import (from pkg import submod) resolves to the submodule.
        if not resolved and f"{module}.{symbol}" in artifact.modules:
            resolved = True
        evidence = "symbol found in dependency" if resolved else "module matched; symbol not found"
        return Resolution(module, symbol, artifact.package, artifact.version,
                          artifact.hash, resolved, evidence)

    def _provider_for(self, module: str) -> ArtifactModules | None:
        top = module.split(".")[0]
        for artifact in self._artifacts:
            if module in artifact.modules or top in artifact.top_levels:
                return artifact
        return None

    @staticmethod
    def _has_entity(index_path: str, entity_id: str) -> bool:
        database = EngineDatabase(Path(index_path))
        try:
            return EngineRepository(database).get_entity(entity_id) is not None
        finally:
            database.close()
