from __future__ import annotations

import json
from typing import Any

from ..storage.db import Database
from ..storage.migrations import utc_now


class SyncState:
    """What Beagle remembers about GitHub: one JSON record for each pull request."""

    def __init__(self, core: Database):
        self.core = core

    def get(self, key: str, default: Any = None) -> Any:
        raw = self.core.scalar("select value from github_sync where key = ?", (key,))
        return json.loads(raw) if raw is not None else default

    def set(self, key: str, value: Any) -> None:
        self.core.execute(
            "insert into github_sync (key, value, updated_at) values (?,?,?)"
            " on conflict(key) do update set value = excluded.value,"
            " updated_at = excluded.updated_at",
            (key, json.dumps(value), utc_now()),
        )

    def pr(self, number: int) -> dict:
        return self.get(f"pr:{number}") or {}

    def update_pr(self, number: int, **changes: Any) -> dict:
        """Change named keys in one transaction.

        The poller and a review worker both write this record, and a review
        holds its copy for as long as posting to GitHub takes. Writing the whole
        record back would erase whatever the other thread stored meanwhile.
        """
        key = f"pr:{number}"
        with self.core.tx() as conn:
            row = conn.execute("select value from github_sync where key = ?", (key,)).fetchone()
            record = json.loads(row[0]) if row else {}
            record.update(changes)
            conn.execute(
                "insert into github_sync (key, value, updated_at) values (?,?,?)"
                " on conflict(key) do update set value = excluded.value,"
                " updated_at = excluded.updated_at",
                (key, json.dumps(record), utc_now()),
            )
        return record

    def forget_pr(self, number: int) -> None:
        self.core.execute("delete from github_sync where key = ?", (f"pr:{number}",))

    def tracked_prs(self) -> list[int]:
        rows = self.core.query("select key from github_sync where key like 'pr:%'")
        return [int(row[0].split(":", 1)[1]) for row in rows]
