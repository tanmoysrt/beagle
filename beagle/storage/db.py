from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import sqlite_vec

from ..errors import MigrationError
from .migrations import Migrator, utc_now

CORE_DB = "beagle.db"
VECTORS_DB = "vectors.db"
LLM_LOG_DB = "llm_log.db"


class Database:
    """One SQLite file, one connection, guarded by a lock.

    A single server process owns every database, so a plain lock is enough and
    keeps transaction boundaries obvious.
    """

    def __init__(self, path: Path, name: str, load_vec: bool = False):
        self.path = path
        self.name = name
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if load_vec:
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
        self.apply_pragmas()

    def apply_pragmas(self) -> None:
        self.conn.execute("pragma journal_mode = WAL")
        self.conn.execute("pragma synchronous = NORMAL")
        self.conn.execute("pragma busy_timeout = 10000")
        self.conn.execute("pragma foreign_keys = ON")

    def migrate(self, substitutions: dict[str, str] | None = None) -> list[str]:
        with self.lock:
            return Migrator(self.conn, self.name, substitutions).run()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.conn.execute("begin")
            try:
                yield self.conn
            except BaseException:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.one(sql, params)
        return row[0] if row is not None else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class Storage:
    """The three databases, split by workload.

    core is small, hot and precious; vectors is most of the bytes and fully
    rebuildable; llm_log is append-only and must never contend with core writes.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.core = Database(self.data_dir / CORE_DB, "core")
        self.vectors = Database(self.data_dir / VECTORS_DB, "vectors", load_vec=True)
        self.llm_log = Database(self.data_dir / LLM_LOG_DB, "llm_log")

    def migrate(self, dims: int) -> dict[str, list[str]]:
        """Core first: it holds the stamp that says what vectors.db was built for."""
        ran = {"core": self.core.migrate()}
        existing = self.vector_dims()
        if existing is not None and existing != dims:
            raise MigrationError(
                f"vectors.db was built for {existing} dimensions but config asks for {dims}; "
                "delete vectors.db to re-embed in the new space"
            )
        ran["vectors"] = self.vectors.migrate({"dims": str(dims)})
        ran["llm_log"] = self.llm_log.migrate()
        self.stamp("vector_dims", str(dims))
        return ran

    def stamp(self, key: str, value: str) -> None:
        self.core.execute(
            "insert into config_stamps (key, value, updated_at) values (?,?,?) "
            "on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at",
            (key, value, utc_now()),
        )

    def stamp_value(self, key: str) -> str | None:
        return self.core.scalar("select value from config_stamps where key = ?", (key,))

    def vector_dims(self) -> int | None:
        stamp = self.stamp_value("vector_dims")
        return int(stamp) if stamp else None

    def close(self) -> None:
        for database in (self.core, self.vectors, self.llm_log):
            database.close()


def open_storage(data_dir: Path | str, dims: int) -> Storage:
    storage = Storage(data_dir)
    storage.migrate(dims)
    return storage
