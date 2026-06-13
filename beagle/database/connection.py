"""SQLite connection wrapper: open, migrate, and own-file deletion.

Higher layers (persistence/repository) build on this. This module knows about
the connection, pragmas, and migrations only — no extraction or graph logic.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from beagle.database.migrations import LATEST_VERSION, MIGRATIONS

# Tables whose rows carry an ``owner_file`` column. Deleting a file purges
# every row in these tables that names it as owner, in one transaction.
_OWNED_TABLES = ("edges", "observations", "entities", "text_chunks")


class Database:
    """Thin SQLite wrapper with migrations and foreign keys always enabled."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            " version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        done = {
            row["version"]
            for row in self.conn.execute("SELECT version FROM schema_versions")
        }
        for version, sql in MIGRATIONS:
            if version in done:
                continue
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_versions(version, applied_at) VALUES (?, ?)",
                    (version, time.time()),
                )

    @property
    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM schema_versions"
        ).fetchone()
        return row["v"] or 0

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block atomically; commit on success, roll back on error."""
        with self.conn:
            yield self.conn

    def delete_file_facts(self, conn: sqlite3.Connection, path: str) -> None:
        """Remove every fact owned by ``path``. Caller supplies the transaction.

        Keyed on ``owner_file`` so no fact extracted from this file survives a
        change or deletion, satisfying the zero-stale-facts requirement.
        """
        for table in _OWNED_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE owner_file = ?", (path,))
        conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
