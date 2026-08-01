from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..errors import MigrationError

SCHEMA_ROOT = Path(__file__).parent / "schema"


@dataclass(frozen=True)
class Patch:
    number: int
    name: str
    sql: str
    checksum: str


class Migrator:
    """Applies ordered .sql patches to one database and records what it ran.

    Startup refuses to continue on a checksum mismatch or a database newer than
    the code, rather than guessing what changed.
    """

    def __init__(self, conn: sqlite3.Connection, name: str, substitutions: dict[str, str] | None = None):
        self.conn = conn
        self.name = name
        self.substitutions = substitutions or {}
        self.directory = SCHEMA_ROOT / name

    def run(self) -> list[str]:
        patches = self.load_patches()
        self.ensure_ledger()
        applied = self.applied_patches()
        self.check_not_newer(patches, applied)

        run_now = []
        for patch in patches:
            recorded = applied.get(patch.number)
            if recorded is None:
                self.apply(patch)
                run_now.append(f"{self.name}/{patch.number:03d}_{patch.name}")
            elif recorded != patch.checksum:
                raise MigrationError(
                    f"{self.name}: migration {patch.number:03d}_{patch.name} was applied "
                    f"with a different checksum ({recorded[:12]} on disk vs {patch.checksum[:12]} "
                    "in this build) — the database and the code disagree"
                )
        return run_now

    def load_patches(self) -> list[Patch]:
        if not self.directory.is_dir():
            raise MigrationError(f"no schema directory for {self.name}")
        patches = []
        for path in sorted(self.directory.glob("*.sql")):
            number, _, name = path.stem.partition("_")
            raw = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(raw.encode()).hexdigest()
            patches.append(Patch(int(number), name, self.substitute(raw), checksum))
        if not patches:
            raise MigrationError(f"no migrations found in {self.directory}")
        return patches

    def substitute(self, sql: str) -> str:
        for key, value in self.substitutions.items():
            sql = sql.replace("{" + key + "}", str(value))
        return sql

    def ensure_ledger(self) -> None:
        self.conn.execute(
            "create table if not exists migrations ("
            " number integer primary key, name text not null,"
            " checksum text not null, applied_at text not null)"
        )

    def applied_patches(self) -> dict[int, str]:
        rows = self.conn.execute("select number, checksum from migrations").fetchall()
        return {row[0]: row[1] for row in rows}

    def check_not_newer(self, patches: list[Patch], applied: dict[int, str]) -> None:
        highest_known = patches[-1].number
        unknown = [number for number in applied if number > highest_known]
        if unknown:
            raise MigrationError(
                f"{self.name}: database has migration {max(unknown):03d} but this build "
                f"only knows up to {highest_known:03d} — downgrade is not supported"
            )

    def apply(self, patch: Patch) -> None:
        try:
            self.conn.execute("begin")
            for statement in split_statements(patch.sql):
                self.conn.execute(statement)
            self.conn.execute(
                "insert into migrations (number, name, checksum, applied_at) values (?,?,?,?)",
                (patch.number, patch.name, patch.checksum, utc_now()),
            )
            self.conn.execute(f"pragma user_version = {patch.number}")
            self.conn.commit()
        except sqlite3.Error as exc:
            self.conn.rollback()
            raise MigrationError(
                f"{self.name}: migration {patch.number:03d}_{patch.name} failed: {exc}"
            ) from exc


def split_statements(sql: str) -> list[str]:
    """Split a patch into statements so the whole patch can run in one transaction.

    executescript would commit first, which would cost us atomicity, so lean on
    sqlite's own parser to find statement boundaries.
    """
    statements, buffer = [], ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise MigrationError(f"patch ends mid-statement: {buffer.strip()[:60]}…")
    return statements


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
