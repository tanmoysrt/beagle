from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from .db import Database
from .migrations import utc_now


class IndexStore:
    """Reads and writes for the structural index."""

    def __init__(self, core: Database):
        self.core = core

    def known_hashes(self) -> dict[str, str]:
        return {row[0]: row[1] for row in self.core.query("select path, content_hash from files")}

    def known_paths(self) -> set[str]:
        return {row[0] for row in self.core.query("select path from files")}

    def replace_file(self, path: str, lang: str | None, blob_sha: str, content_hash: str, size: int) -> int:
        """Drop everything derived from a file, then re-register it."""
        with self.core.tx() as conn:
            conn.execute("delete from files where path = ?", (path,))
            cursor = conn.execute(
                "insert into files (path, lang, blob_sha, content_hash, size_bytes, indexed_at) "
                "values (?,?,?,?,?,?)",
                (path, lang, blob_sha, content_hash, size, utc_now()),
            )
            return int(cursor.lastrowid)

    def chunk_ids_for_path(self, path: str) -> list[int]:
        return [row[0] for row in self.core.query("select id from chunks where path = ?", (path,))]

    def delete_file(self, path: str) -> None:
        self.core.execute("delete from files where path = ?", (path,))

    def insert_symbols(self, file_id: int, rows: Sequence[dict[str, Any]]) -> dict[str, int]:
        """Insert symbols parent-first so nested symbols can point at their parent."""
        ids: dict[str, int] = {}
        with self.core.tx() as conn:
            for row in rows:
                parent_id = ids.get(row["parent_key"]) if row.get("parent_key") else None
                cursor = conn.execute(
                    "insert into symbols (file_id, parent_id, name, qualified_name, kind, lang,"
                    " signature, start_line, end_line, start_byte, end_byte)"
                    " values (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        file_id,
                        parent_id,
                        row["name"],
                        row["qualified_name"],
                        row["kind"],
                        row["lang"],
                        row["signature"],
                        row["start_line"],
                        row["end_line"],
                        row["start_byte"],
                        row["end_byte"],
                    ),
                )
                ids[row["key"]] = int(cursor.lastrowid)
        return ids

    def insert_imports(self, file_id: int, rows: Iterable[tuple[str, str | None, str | None, int]]) -> None:
        self.core.executemany(
            "insert into imports (file_id, module, symbol, alias, line) values (?,?,?,?,?)",
            [(file_id, *row) for row in rows],
        )

    def insert_edges(self, rows: Sequence[tuple[int, int | None, str, str, str, int]]) -> None:
        self.core.executemany(
            "insert into symbol_edges (src_symbol_id, dst_symbol_id, dst_name, kind, resolution, line)"
            " values (?,?,?,?,?,?)",
            rows,
        )

    def symbols_by_name(self, names: Sequence[str]) -> list[dict[str, Any]]:
        if not names:
            return []
        placeholders = ",".join("?" * len(names))
        rows = self.core.query(
            f"select s.id, s.name, s.qualified_name, s.file_id, f.path"
            f" from symbols s join files f on f.id = s.file_id where s.name in ({placeholders})",
            list(names),
        )
        return [dict(row) for row in rows]

    def unresolved_edges(self) -> list[tuple[int, str]]:
        rows = self.core.query(
            "select id, dst_name from symbol_edges where dst_symbol_id is null"
        )
        return [(row[0], row[1]) for row in rows]

    def resolve_edges(self, updates: Sequence[tuple[int, str, int]]) -> None:
        """updates: (symbol_id, resolution, edge_id)"""
        self.core.executemany(
            "update symbol_edges set dst_symbol_id = ?, resolution = ? where id = ?", updates
        )

    def symbols_in_file(self, path: str) -> list[dict[str, Any]]:
        rows = self.core.query(
            "select s.* from symbols s join files f on f.id = s.file_id where f.path = ?"
            " order by s.start_line",
            (path,),
        )
        return [dict(row) for row in rows]

    def symbols_overlapping(self, path: str, start_line: int, end_line: int) -> list[dict[str, Any]]:
        rows = self.core.query(
            "select s.* from symbols s join files f on f.id = s.file_id"
            " where f.path = ? and s.start_line <= ? and s.end_line >= ?"
            " order by (s.end_line - s.start_line)",
            (path, end_line, start_line),
        )
        return [dict(row) for row in rows]

    def callers_of(self, symbol_id: int) -> list[dict[str, Any]]:
        rows = self.core.query(
            "select s.*, f.path from symbol_edges e"
            " join symbols s on s.id = e.src_symbol_id"
            " join files f on f.id = s.file_id"
            " where e.dst_symbol_id = ?",
            (symbol_id,),
        )
        return [dict(row) for row in rows]

    def callees_of(self, symbol_id: int) -> list[dict[str, Any]]:
        rows = self.core.query(
            "select s.*, f.path, e.dst_name, e.resolution from symbol_edges e"
            " left join symbols s on s.id = e.dst_symbol_id"
            " left join files f on f.id = s.file_id"
            " where e.src_symbol_id = ?",
            (symbol_id,),
        )
        return [dict(row) for row in rows]

    def insert_chunks(self, rows: Sequence[tuple[int, int | None, str, int, int, str, int, str]]) -> None:
        self.core.executemany(
            "insert or ignore into chunks"
            " (file_id, symbol_id, path, start_line, end_line, content_hash, token_estimate, body)"
            " values (?,?,?,?,?,?,?,?)",
            rows,
        )

    def pending_chunks(self, limit: int) -> list[dict[str, Any]]:
        rows = self.core.query(
            "select id, path, start_line, end_line, body from chunks where embedded = 0 limit ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def pending_chunk_count(self) -> int:
        return int(self.core.scalar("select count(*) from chunks where embedded = 0") or 0)

    def mark_embedded(self, chunk_ids: Sequence[int]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" * len(chunk_ids))
        self.core.execute(
            f"update chunks set embedded = 1 where id in ({placeholders})", list(chunk_ids)
        )

    def chunks_by_ids(self, chunk_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        rows = self.core.query(
            f"select id, path, start_line, end_line, body, symbol_id from chunks"
            f" where id in ({placeholders})",
            list(chunk_ids),
        )
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        tables = ("files", "symbols", "symbol_edges", "chunks", "imports")
        return {
            table: int(self.core.scalar(f"select count(*) from {table}") or 0) for table in tables
        }

    def set_state(self, key: str, value: Any) -> None:
        self.core.execute(
            "insert into index_state (key, value, updated_at) values (?,?,?)"
            " on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), utc_now()),
        )

    def get_state(self, key: str, default: Any = None) -> Any:
        raw = self.core.scalar("select value from index_state where key = ?", (key,))
        return json.loads(raw) if raw is not None else default


class CallLog:
    """Append-only record of every paid API call, for audit, cost and calibration."""

    def __init__(self, llm_log: Database):
        self.llm_log = llm_log

    def record(
        self,
        request_hash: str,
        model: str,
        request: dict[str, Any],
        response: dict[str, Any] | None = None,
        prompt_name: str | None = None,
        prompt_set_version: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        tokens_cached: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int | None = None,
        review_id: str | None = None,
        unit: str | None = None,
        error: str | None = None,
    ) -> None:
        self.llm_log.execute(
            "insert into llm_calls (request_hash, prompt_name, prompt_set_version, model,"
            " tokens_in, tokens_out, tokens_cached, cost_usd, latency_ms, ok, error,"
            " review_id, unit, request_json, response_json, created_at)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request_hash,
                prompt_name,
                prompt_set_version,
                model,
                tokens_in,
                tokens_out,
                tokens_cached,
                cost_usd,
                latency_ms,
                0 if error else 1,
                error,
                review_id,
                unit,
                json.dumps(request)[:200000],
                json.dumps(response)[:400000] if response is not None else None,
                utc_now(),
            ),
        )

    def find(
        self, request_hash: str, prompt_set_version: str | None, review_id: str | None = None
    ) -> dict[str, Any] | None:
        """The answer to an identical question asked in this same review.

        Scoped to the review because two pull requests that happen to carry the
        same diff are still two pull requests, and the second one deserves to be
        read rather than handed the first one's answer.
        """
        row = self.llm_log.one(
            "select response_json from llm_calls where request_hash = ?"
            " and prompt_set_version is ? and review_id is ? and ok = 1"
            " and response_json is not null order by id desc limit 1",
            (request_hash, prompt_set_version, review_id),
        )
        return json.loads(row[0]) if row else None

    def trim(self, days: int) -> int:
        """Drop old calls; the log holds whole prompts and responses."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        cursor = self.llm_log.execute("delete from llm_calls where created_at < ?", (cutoff,))
        removed = cursor.rowcount or 0
        if removed:
            self.llm_log.execute("vacuum")
        return removed

    def spend(self, review_id: str) -> dict[str, float]:
        row = self.llm_log.one(
            "select coalesce(sum(cost_usd),0), coalesce(sum(tokens_in),0),"
            " coalesce(sum(tokens_out),0), coalesce(sum(tokens_cached),0), count(*)"
            " from llm_calls where review_id = ?",
            (review_id,),
        )
        return {
            "cost_usd": round(row[0], 6),
            "tokens_in": row[1],
            "tokens_out": row[2],
            "tokens_cached": row[3],
            "calls": row[4],
        }
