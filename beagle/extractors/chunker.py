"""Baseline text chunking for FTS.

Used when no structural extractor produces entity-aligned chunks. Splits a
file into fixed line windows so lexical search has something to match. Later
stages attach chunks to entities for sharper results.
"""

from __future__ import annotations

from beagle.models import SourceRange, TextChunk

_WINDOW_LINES = 40


def chunk_text(owner_file: str, text: str, window: int = _WINDOW_LINES) -> list[TextChunk]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[TextChunk] = []
    for start in range(0, len(lines), window):
        block = lines[start : start + window]
        content = "\n".join(block)
        if not content.strip():
            continue
        chunks.append(
            TextChunk(
                owner_file=owner_file,
                kind="window",
                content=content,
                source_range=SourceRange(start + 1, 0, start + len(block), 0),
            )
        )
    return chunks
