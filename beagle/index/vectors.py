from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import sqlite_vec

from ..storage.db import Database
from ..storage.migrations import utc_now


@dataclass(frozen=True)
class Neighbour:
    key: int
    distance: float

    @property
    def similarity(self) -> float:
        """vec0 returns L2 distance on normalised vectors; map it back to cosine."""
        return max(0.0, 1.0 - (self.distance**2) / 2.0)


class VectorStore:
    """sqlite-vec tables for chunk and finding embeddings.

    This file is most of the bytes on disk and is fully rebuildable, which is
    why it lives apart from the core database.
    """

    def __init__(self, vectors: Database, dims: int):
        self.vectors = vectors
        self.dims = dims

    def upsert_chunks(self, rows: Sequence[tuple[int, Sequence[float]]]) -> None:
        if not rows:
            return
        with self.vectors.tx() as conn:
            for chunk_id, vector in rows:
                conn.execute("delete from chunk_vectors where chunk_id = ?", (chunk_id,))
                conn.execute(
                    "insert into chunk_vectors (chunk_id, embedding) values (?, ?)",
                    (chunk_id, sqlite_vec.serialize_float32(normalize(vector))),
                )

    def delete_chunks(self, chunk_ids: Sequence[int]) -> None:
        if not chunk_ids:
            return
        self.vectors.executemany(
            "delete from chunk_vectors where chunk_id = ?", [(cid,) for cid in chunk_ids]
        )

    def search_chunks(self, vector: Sequence[float], k: int = 5) -> list[Neighbour]:
        rows = self.vectors.query(
            "select chunk_id, distance from chunk_vectors"
            " where embedding match ? and k = ? order by distance",
            (sqlite_vec.serialize_float32(normalize(vector)), k),
        )
        return [Neighbour(row[0], row[1]) for row in rows]

    def upsert_finding(
        self, finding_id: str, fingerprint: str, category: str, vector: Sequence[float]
    ) -> None:
        with self.vectors.tx() as conn:
            row = conn.execute(
                "select rowid_ref from finding_vector_keys where finding_id = ?", (finding_id,)
            ).fetchone()
            if row:
                key = row[0]
                conn.execute("delete from finding_vectors where finding_rowid = ?", (key,))
            else:
                key = int(
                    conn.execute("select coalesce(max(rowid_ref), 0) + 1 from finding_vector_keys")
                    .fetchone()[0]
                )
                conn.execute(
                    "insert into finding_vector_keys (rowid_ref, finding_id, fingerprint, category,"
                    " created_at) values (?,?,?,?,?)",
                    (key, finding_id, fingerprint, category, utc_now()),
                )
            conn.execute(
                "insert into finding_vectors (finding_rowid, embedding) values (?, ?)",
                (key, sqlite_vec.serialize_float32(normalize(vector))),
            )

    def search_findings(
        self, vector: Sequence[float], k: int = 10, category: str | None = None
    ) -> list[tuple[str, float]]:
        rows = self.vectors.query(
            "select k.finding_id, v.distance, k.category from finding_vectors v"
            " join finding_vector_keys k on k.rowid_ref = v.finding_rowid"
            " where v.embedding match ? and k = ? order by v.distance",
            (sqlite_vec.serialize_float32(normalize(vector)), k),
        )
        matches = [(row[0], Neighbour(0, row[1]).similarity) for row in rows if category in (None, row[2])]
        return matches

    def counts(self) -> dict[str, int]:
        return {
            "chunk_vectors": int(self.vectors.scalar("select count(*) from chunk_vectors") or 0),
            "finding_vectors": int(self.vectors.scalar("select count(*) from finding_vectors") or 0),
        }


def normalize(vector: Sequence[float]) -> list[float]:
    total = sum(value * value for value in vector) ** 0.5
    if total == 0:
        return list(vector)
    return [value / total for value in vector]
