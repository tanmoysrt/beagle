"""Plain data records passed between layers.

These are dumb containers. Discovery produces ``DiscoveredFile``; extraction
produces ``Entity``/``Observation``/``TextChunk``; resolution produces ``Edge``.
Persistence reads and writes them. No layer puts behaviour here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SourceRange:
    """1-based inclusive line range with 0-based columns, as LibCST reports."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def empty(cls) -> "SourceRange":
        return cls(0, 0, 0, 0)


@dataclass(frozen=True)
class DiscoveredFile:
    """A file found on disk that beagle is willing to index."""

    relpath: str
    abspath: str
    language: str
    hash: str
    size: int
    mtime: float
    module: Optional[str] = None


@dataclass
class FileRecord:
    """A file as persisted in the database."""

    path: str
    language: str
    hash: str
    size: int
    mtime: float
    id: Optional[int] = None
    run_id: Optional[int] = None


@dataclass
class Entity:
    """A named thing in source: module, class, function, doctype, field, etc.

    ``id`` is a stable identifier that never includes line numbers, so it
    survives edits that move the entity within its file.
    """

    id: str
    kind: str
    name: str
    qualified_name: str
    owner_file: str
    source_range: SourceRange
    signature: Optional[str] = None
    docstring: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    """A raw parser fact, stored before resolution.

    ``subject`` is the entity id of the enclosing scope (e.g. the method that
    contains a call). ``data`` holds the raw parsed shape (callee expression,
    imported name, base-class expression, ...).
    """

    kind: str
    owner_file: str
    subject: str
    source_range: SourceRange
    data: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class Edge:
    """A resolved (or deliberately unresolved) relationship between entities.

    When resolution fails, ``target_id`` is ``None`` and ``target_hint`` keeps
    the raw symbol so the observation is never silently dropped or upgraded to
    a confirmed fact.
    """

    source_id: str
    relationship: str
    confidence: float
    resolver: str
    resolver_version: str
    owner_file: str
    source_range: SourceRange
    target_id: Optional[str] = None
    target_hint: Optional[str] = None
    observation_id: Optional[int] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None


@dataclass
class TextChunk:
    """A searchable slice of source text, optionally tied to an entity."""

    owner_file: str
    kind: str
    content: str
    source_range: SourceRange
    entity_id: Optional[str] = None
    id: Optional[int] = None
