from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .graph import symbol_key
from .symbols import Symbol

MAX_CHUNK_CHARS = 6000
MIN_CHUNK_CHARS = 40
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int
    end_line: int
    body: str
    content_hash: str
    token_estimate: int
    symbol_key: str | None


def chunk_file(path: str, source: str, symbols: list[Symbol]) -> list[Chunk]:
    """Chunk by symbol, not by line count, so retrieved context is self-contained."""
    lines = source.splitlines()
    if not lines:
        return []

    top_level = [symbol for symbol in symbols if symbol.parent is None]
    if not top_level:
        return whole_file_chunks(path, lines)

    chunks = [make_chunk(path, symbol, lines) for symbol in top_level]
    chunks.extend(preamble_chunk(path, top_level, lines))
    return [chunk for chunk in chunks if chunk is not None]


def make_chunk(path: str, symbol: Symbol, lines: list[str]) -> Chunk | None:
    body = "\n".join(lines[symbol.start_line - 1 : symbol.end_line])
    return build(path, symbol.start_line, symbol.end_line, body, symbol_key(path, symbol))


def preamble_chunk(path: str, top_level: list[Symbol], lines: list[str]) -> list[Chunk]:
    """Imports and module-level setup above the first definition still matter."""
    first_line = min(symbol.start_line for symbol in top_level)
    if first_line <= 1:
        return []
    body = "\n".join(lines[: first_line - 1])
    chunk = build(path, 1, first_line - 1, body, None)
    return [chunk] if chunk else []


def whole_file_chunks(path: str, lines: list[str]) -> list[Chunk]:
    chunks, window = [], 120
    for start in range(0, len(lines), window):
        body = "\n".join(lines[start : start + window])
        chunk = build(path, start + 1, min(start + window, len(lines)), body, None)
        if chunk:
            chunks.append(chunk)
    return chunks


def build(path: str, start_line: int, end_line: int, body: str, key: str | None) -> Chunk | None:
    if len(body.strip()) < MIN_CHUNK_CHARS:
        return None
    # Every chunk is one embedding input, and an endpoint rejects an input that
    # is too long, so the cap belongs here and not at each call site.
    if len(body) > MAX_CHUNK_CHARS:
        body = body[:MAX_CHUNK_CHARS] + "\n… truncated …"
    return Chunk(
        path=path,
        start_line=start_line,
        end_line=end_line,
        body=body,
        content_hash=hashlib.sha256(f"{path}:{body}".encode()).hexdigest(),
        token_estimate=max(1, len(body) // CHARS_PER_TOKEN),
        symbol_key=key,
    )
