"""Database abstraction over SQLite and PostgreSQL.

The service runs on PostgreSQL in production (design/15 §22) and on SQLite for
tests, standalone mode, and worker scratch. Both speak the same portable SQL;
this layer hides the two differences that matter to callers:

- placeholder style (``?`` for SQLite, ``%s`` for psycopg);
- row shape (rows are always returned as plain ``dict`` objects).

Stores depend only on :class:`Connection`. They never import a driver directly.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from beagle.service.schema import MIGRATIONS


class Connection:
    """A single open connection with placeholder + row normalization."""

    def __init__(self, raw: Any, dialect: str):
        self._raw = raw
        self._dialect = dialect

    def _render(self, sql: str) -> str:
        if self._dialect == "postgres":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        cursor = self._raw.cursor()
        cursor.execute(self._render(sql), tuple(params))

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        cursor = self._raw.cursor()
        cursor.execute(self._render(sql), tuple(params))
        row = cursor.fetchone()
        return self._to_dict(cursor, row)

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        cursor = self._raw.cursor()
        cursor.execute(self._render(sql), tuple(params))
        rows = cursor.fetchall()
        return [self._to_dict(cursor, row) for row in rows]

    @staticmethod
    def _to_dict(cursor: Any, row: Any) -> dict | None:
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        if isinstance(row, sqlite3.Row):
            return {key: row[key] for key in row.keys()}
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))


class Database:
    """Opens connections and runs migrations for one configured database URL."""

    def __init__(self, url: str):
        self.url = url
        self.dialect = "sqlite" if url.startswith("sqlite") else "postgres"
        self._sqlite_path = self._parse_sqlite_path(url) if self.dialect == "sqlite" else None
        self._dsn = url if self.dialect == "postgres" else None

    @staticmethod
    def _parse_sqlite_path(url: str) -> str:
        path = url[len("sqlite://"):]
        if path.startswith("/"):
            path = path[1:]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return path or ":memory:"

    def _open(self) -> tuple[Any, str]:
        if self.dialect == "sqlite":
            raw = sqlite3.connect(self._sqlite_path)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys = ON")
            return raw, "sqlite"
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(self._dsn, row_factory=dict_row)
        return raw, "postgres"

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """Yield a connection; commit on success, roll back on error."""
        raw, dialect = self._open()
        try:
            yield Connection(raw, dialect)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS service_schema_versions ("
                " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {
                row["version"]
                for row in conn.fetch_all("SELECT version FROM service_schema_versions")
            }
            for version, statements in MIGRATIONS:
                if version in done:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO service_schema_versions(version, applied_at)"
                    " VALUES (?, datetime('now'))"
                    if self.dialect == "sqlite"
                    else "INSERT INTO service_schema_versions(version, applied_at)"
                    " VALUES (?, now())",
                    (version,),
                )
