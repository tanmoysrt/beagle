"""Dependency analysis (design/15 §11–§14).

Parses Python and JavaScript manifests/lockfiles into pinned dependency
snapshots and provides the safe-acquisition primitives (hash verification,
archive-safe extraction). No dependency code is ever executed: there are no
install or lifecycle scripts here, only parsing and verified unpacking.
"""

from dataclasses import dataclass


@dataclass
class ParsedPackage:
    """One resolved dependency, anchored on (ecosystem, name, version)."""

    ecosystem: str          # "python" | "javascript"
    name: str
    version: str
    hash: str | None        # artifact integrity hash when the lockfile pins one
    source_type: str        # wheel | sdist | registry | git | manifest
    group: str              # default | dev | ...
