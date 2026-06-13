"""Lexical search over indexed source via SQLite FTS5.

Ranking only; it does not parse or resolve. Returns chunk hits with their
owner file, source range, and (when available) the entity they belong to so a
caller can read the exact lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from beagle.database import Database
from beagle.models import SourceRange

# Strip FTS5 syntax characters so arbitrary user text can't form a bad query.
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class SearchResult:
    owner_file: str
    entity_id: Optional[str]
    kind: str
    snippet: str
    source_range: SourceRange
    score: float


def _build_match(query: str, prefix: bool = False) -> str:
    """OR the tokens so any term can match (recall-friendly).

    With ``prefix`` each token becomes a prefix query (``tok*``), which catches
    compound identifiers like ``DNSValidationError`` from the term ``DNS`` —
    useful for issue investigation.
    """
    tokens = _TOKEN.findall(query)
    if prefix:
        return " OR ".join(f'"{t}"*' for t in tokens)
    return " OR ".join(f'"{t}"' for t in tokens)


class SearchEngine:
    def __init__(self, db: Database):
        self.conn = db.conn

    def search(self, query: str, limit: int = 10, prefix: bool = False) -> list[SearchResult]:
        match = _build_match(query, prefix=prefix)
        if not match:
            return []
        rows = self.conn.execute(
            "SELECT c.owner_file, c.entity_id, c.kind, c.content, "
            "c.start_line, c.start_col, c.end_line, c.end_col, "
            "bm25(fts_chunks) AS score "
            "FROM fts_chunks JOIN text_chunks c ON c.id = fts_chunks.rowid "
            "WHERE fts_chunks MATCH ? ORDER BY score LIMIT ?",
            (match, limit),
        ).fetchall()
        return [
            SearchResult(
                owner_file=row["owner_file"],
                entity_id=row["entity_id"],
                kind=row["kind"],
                snippet=self._snippet(row["content"]),
                source_range=SourceRange(
                    row["start_line"], row["start_col"], row["end_line"], row["end_col"]
                ),
                score=row["score"],
            )
            for row in rows
        ]

    @staticmethod
    def _snippet(content: str, max_lines: int = 3) -> str:
        lines = [ln for ln in content.splitlines() if ln.strip()]
        return "\n".join(lines[:max_lines])
