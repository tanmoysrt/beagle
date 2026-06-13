"""Indexing orchestration.

The workspace ties discovery, extraction, persistence, and (later) resolution
together. The CLI and MCP server both go through it so they share one code
path. It computes the change set, deletes stale facts per file, and stores
fresh ones, keeping incremental updates free of stale data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from beagle.database import Database
from beagle.database.repository import Repository
from beagle.discovery import Scanner, find_repo_root
from beagle.extractors import extract_file
from beagle.models import DiscoveredFile, FileRecord
from beagle.resolution import resolve_workspace

_DB_DIRNAME = ".beagle"
_DB_FILENAME = "index.db"


class Workspace:
    """A single indexed repository rooted at ``root`` with its SQLite index."""

    def __init__(self, root: Path, db_path: Optional[Path] = None):
        self.root = root.resolve()
        self.db_path = db_path or (self.root / _DB_DIRNAME / _DB_FILENAME)
        self.db = Database(self.db_path)
        self.repo = Repository(self.db)

    @classmethod
    def locate(cls, start: Path) -> "Workspace":
        """Open the workspace for the repo containing ``start``."""
        return cls(find_repo_root(start))

    def close(self) -> None:
        self.db.close()

    # --- indexing ------------------------------------------------------

    def index(self, force: bool = False) -> dict:
        run_id = self.repo.start_run(str(self.root))
        discovered = {d.relpath: d for d in Scanner(self.root).scan()}
        existing = self.repo.existing_files()

        changed = [
            d for path, d in discovered.items()
            if force or existing.get(path) != d.hash
        ]
        deleted = [path for path in existing if path not in discovered]

        for path in deleted:
            with self.db.transaction() as conn:
                self.db.delete_file_facts(conn, path)

        for d in changed:
            self._index_file(d, run_id)

        # Resolution is a cross-file pass; rerun it whenever anything moved.
        touched = bool(changed or deleted)
        if touched:
            resolve_workspace(self.db, self.repo)

        summary = {
            "indexed": len(changed),
            "deleted": len(deleted),
            "unchanged": len(discovered) - len(changed),
            "total_files": len(discovered),
        }
        self.repo.finish_run(run_id, "complete", len(changed), summary)
        return summary

    def _index_file(self, discovered: DiscoveredFile, run_id: int) -> None:
        try:
            text = Path(discovered.abspath).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        result = extract_file(discovered, text)
        record = FileRecord(
            path=discovered.relpath,
            language=discovered.language,
            hash=discovered.hash,
            size=discovered.size,
            mtime=discovered.mtime,
            run_id=run_id,
        )
        with self.db.transaction() as conn:
            self.db.delete_file_facts(conn, discovered.relpath)
            self.repo.upsert_file(conn, record)
            self.repo.insert_entities(conn, result.entities)
            self.repo.insert_observations(conn, result.observations)
            self.repo.insert_chunks(conn, result.chunks)

    # --- reading -------------------------------------------------------

    def read_range(self, relpath: str, start_line: int, end_line: int) -> str:
        path = self.root / relpath
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(start_line - 1, 0)
        hi = min(end_line, len(lines))
        return "\n".join(lines[lo:hi])
