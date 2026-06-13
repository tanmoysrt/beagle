"""Persistence: turn records into rows and back.

This is the only module that writes the graph tables. Extraction and
resolution hand it records; retrieval reads through its query helpers. It does
no parsing and no ranking.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Iterable, Optional

from beagle.database.connection import Database
from beagle.models import Edge, Entity, FileRecord, Observation, SourceRange, TextChunk


def _edge_from_row(row: sqlite3.Row) -> Edge:
    return Edge(
        source_id=row["source_id"],
        relationship=row["relationship"],
        confidence=row["confidence"],
        resolver=row["resolver"],
        resolver_version=row["resolver_version"],
        owner_file=row["owner_file"],
        source_range=SourceRange(
            row["start_line"], row["start_col"], row["end_line"], row["end_col"]
        ),
        target_id=row["target_id"],
        target_hint=row["target_hint"],
        observation_id=row["observation_id"],
        evidence=json.loads(row["evidence_json"]) if row["evidence_json"] else {},
        id=row["id"],
    )


def _range_cols(r: SourceRange) -> tuple[int, int, int, int]:
    return (r.start_line, r.start_col, r.end_line, r.end_col)


def _row_range(row: sqlite3.Row) -> SourceRange:
    return SourceRange(
        row["start_line"], row["start_col"], row["end_line"], row["end_col"]
    )


class Repository:
    """Read/write access to files, entities, observations, edges, chunks."""

    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn

    # --- index runs ----------------------------------------------------

    def start_run(self, root: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO index_runs(root, started_at, status) VALUES (?, ?, ?)",
            (root, time.time(), "running"),
        )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, files_indexed: int, summary: dict) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE index_runs SET finished_at = ?, status = ?, "
                "files_indexed = ?, summary_json = ? WHERE id = ?",
                (time.time(), status, files_indexed, json.dumps(summary), run_id),
            )

    def latest_run(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # --- files ---------------------------------------------------------

    def existing_files(self) -> dict[str, str]:
        """Map of path -> hash for every currently indexed file."""
        return {
            row["path"]: row["hash"]
            for row in self.conn.execute("SELECT path, hash FROM files")
        }

    def upsert_file(self, conn: sqlite3.Connection, record: FileRecord) -> None:
        conn.execute(
            "INSERT INTO files(path, language, hash, size, mtime, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET language=excluded.language, "
            "hash=excluded.hash, size=excluded.size, mtime=excluded.mtime, "
            "run_id=excluded.run_id",
            (record.path, record.language, record.hash, record.size,
             record.mtime, record.run_id),
        )

    # --- writing facts -------------------------------------------------

    def insert_entities(self, conn: sqlite3.Connection, entities: Iterable[Entity]) -> None:
        for e in entities:
            conn.execute(
                "INSERT OR REPLACE INTO entities(id, kind, name, qualified_name, "
                "owner_file, start_line, start_col, end_line, end_col, signature, "
                "docstring, extra_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (e.id, e.kind, e.name, e.qualified_name, e.owner_file,
                 *_range_cols(e.source_range), e.signature, e.docstring,
                 json.dumps(e.extra) if e.extra else None),
            )

    def insert_observations(
        self, conn: sqlite3.Connection, observations: Iterable[Observation]
    ) -> list[int]:
        ids: list[int] = []
        for o in observations:
            cur = conn.execute(
                "INSERT INTO observations(kind, owner_file, subject, start_line, "
                "start_col, end_line, end_col, data_json) VALUES (?,?,?,?,?,?,?,?)",
                (o.kind, o.owner_file, o.subject, *_range_cols(o.source_range),
                 json.dumps(o.data) if o.data else None),
            )
            o.id = int(cur.lastrowid)
            ids.append(o.id)
        return ids

    def insert_edges(self, conn: sqlite3.Connection, edges: Iterable[Edge]) -> None:
        for e in edges:
            conn.execute(
                "INSERT INTO edges(source_id, target_id, target_hint, relationship, "
                "confidence, resolver, resolver_version, observation_id, owner_file, "
                "start_line, start_col, end_line, end_col, evidence_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (e.source_id, e.target_id, e.target_hint, e.relationship,
                 e.confidence, e.resolver, e.resolver_version, e.observation_id,
                 e.owner_file, *_range_cols(e.source_range),
                 json.dumps(e.evidence) if e.evidence else None),
            )

    def insert_chunks(self, conn: sqlite3.Connection, chunks: Iterable[TextChunk]) -> None:
        for c in chunks:
            conn.execute(
                "INSERT INTO text_chunks(owner_file, entity_id, kind, content, "
                "start_line, start_col, end_line, end_col) VALUES (?,?,?,?,?,?,?,?)",
                (c.owner_file, c.entity_id, c.kind, c.content, *_range_cols(c.source_range)),
            )

    # --- reads ---------------------------------------------------------

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("files", "entities", "observations", "edges", "text_chunks"):
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = row["n"]
        return out

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        row = self.conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        return self._entity_from_row(row) if row else None

    def iter_entities(self) -> list[Entity]:
        rows = self.conn.execute("SELECT * FROM entities").fetchall()
        return [self._entity_from_row(r) for r in rows]

    def observations_of_kind(self, kind: str) -> list[Observation]:
        rows = self.conn.execute(
            "SELECT * FROM observations WHERE kind = ?", (kind,)
        ).fetchall()
        return [self._observation_from_row(r) for r in rows]

    def observations_for_subjects(
        self, subjects: list[str], kinds: tuple[str, ...]
    ) -> list[Observation]:
        if not subjects or not kinds:
            return []
        sp = ",".join("?" * len(subjects))
        kp = ",".join("?" * len(kinds))
        rows = self.conn.execute(
            f"SELECT * FROM observations WHERE subject IN ({sp}) AND kind IN ({kp})",
            (*subjects, *kinds),
        ).fetchall()
        return [self._observation_from_row(r) for r in rows]

    def entities_overlapping(
        self, relpath: str, start: int, end: int, kinds: tuple[str, ...]
    ) -> list[Entity]:
        kp = ",".join("?" * len(kinds))
        rows = self.conn.execute(
            f"SELECT * FROM entities WHERE owner_file = ? AND kind IN ({kp}) "
            f"AND end_line >= ? AND start_line <= ?",
            (relpath, *kinds, start, end),
        ).fetchall()
        return [self._entity_from_row(r) for r in rows]

    def entity_containing(
        self, relpath: str, line: int, kinds: Optional[tuple[str, ...]] = None
    ) -> Optional[Entity]:
        sql = ("SELECT * FROM entities WHERE owner_file = ? AND start_line <= ? "
               "AND end_line >= ?")
        params: list = [relpath, line, line]
        if kinds:
            sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            params += list(kinds)
        sql += " ORDER BY (end_line - start_line) ASC LIMIT 1"
        row = self.conn.execute(sql, params).fetchone()
        return self._entity_from_row(row) if row else None

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> Observation:
        return Observation(
            kind=row["kind"],
            owner_file=row["owner_file"],
            subject=row["subject"],
            source_range=_row_range(row),
            data=json.loads(row["data_json"]) if row["data_json"] else {},
            id=row["id"],
        )

    def delete_all_edges(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM edges")

    def edges_from(self, source_id: str, relationships: Optional[tuple[str, ...]] = None) -> list[Edge]:
        return self._edges("source_id", source_id, relationships)

    def edges_to(self, target_id: str, relationships: Optional[tuple[str, ...]] = None) -> list[Edge]:
        return self._edges("target_id", target_id, relationships)

    def _edges(self, column: str, value: str, relationships: Optional[tuple[str, ...]]) -> list[Edge]:
        sql = f"SELECT * FROM edges WHERE {column} = ?"
        params: list = [value]
        if relationships:
            sql += " AND relationship IN (%s)" % ",".join("?" * len(relationships))
            params += list(relationships)
        sql += " ORDER BY relationship, confidence DESC"
        return [_edge_from_row(r) for r in self.conn.execute(sql, params).fetchall()]

    def entities_by_id_prefix(self, prefix: str, limit: int = 50) -> list[Entity]:
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE id LIKE ? ESCAPE '\\' ORDER BY start_line LIMIT ?",
            (prefix.replace("%", "\\%").replace("_", "\\_") + "%", limit),
        ).fetchall()
        return [self._entity_from_row(r) for r in rows]

    def entities_in_file(self, relpath: str, kinds: Optional[tuple[str, ...]] = None) -> list[Entity]:
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            rows = self.conn.execute(
                f"SELECT * FROM entities WHERE owner_file = ? AND kind IN ({placeholders})",
                (relpath, *kinds),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM entities WHERE owner_file = ?", (relpath,)
            ).fetchall()
        return [self._entity_from_row(r) for r in rows]

    def find_entities_by_name(self, name: str, limit: int = 50) -> list[Entity]:
        # Exact name / qualified name, plus dotted-suffix match so "Order.book"
        # finds "<module>.Order.book".
        suffix = "%." + name.replace("%", "\\%").replace("_", "\\_") if "." in name else name
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? OR qualified_name = ? "
            "OR qualified_name LIKE ? ESCAPE '\\' "
            "ORDER BY length(qualified_name) LIMIT ?",
            (name, name, suffix, limit),
        ).fetchall()
        return [self._entity_from_row(r) for r in rows]

    @staticmethod
    def _entity_from_row(row: sqlite3.Row) -> Entity:
        return Entity(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            qualified_name=row["qualified_name"],
            owner_file=row["owner_file"],
            source_range=_row_range(row),
            signature=row["signature"],
            docstring=row["docstring"],
            extra=json.loads(row["extra_json"]) if row["extra_json"] else {},
        )
