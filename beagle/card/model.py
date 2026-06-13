"""Structured Function Context Card model (design/12).

Plain data records. Every behavioural item carries a source line so the card
stays inspectable — the renderer shows facts, it never invents prose. Kept
deliberately small: one focused dataclass per card section, no behaviour here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Identity:
    entity_id: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class Responsibility:
    action: str
    subject: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class Entrypoint:
    kind: str  # endpoint | scheduler | doc_event | controller-lifecycle | job | caller
    detail: str
    entity_id: Optional[str] = None


@dataclass
class Guard:
    kind: str  # decorator | throw | threshold | early-return | permission
    text: str
    line: int = 0


@dataclass
class Effect:
    kind: str  # field-read | doctype-read | field-write | status-write | save | insert | ...
    target: str
    line: int = 0
    certainty: str = "resolved"  # resolved | unconfirmed


@dataclass
class ImportantCall:
    name: str
    category: str  # business | persistence | job | external | security | state
    resolved: bool
    line: int = 0


@dataclass
class LifecyclePath:
    operation: str
    doctype: str
    events: list[str] = field(default_factory=list)
    handlers: list[str] = field(default_factory=list)


@dataclass
class ExternalBoundary:
    kind: str  # shell | http | unknown
    detail: str
    line: int = 0


@dataclass
class FailurePath:
    kind: str  # raises | handles | throws | guard-stop
    detail: str
    line: int = 0


@dataclass
class RelatedEntity:
    entity_id: str
    name: str
    kind: str = ""


@dataclass
class FunctionContext:
    identity: Identity
    responsibility: Responsibility
    entrypoints: list[Entrypoint] = field(default_factory=list)
    guards: list[Guard] = field(default_factory=list)
    reads: list[Effect] = field(default_factory=list)
    writes: list[Effect] = field(default_factory=list)
    calls: list[ImportantCall] = field(default_factory=list)
    lifecycle: list[LifecyclePath] = field(default_factory=list)
    jobs: list[Effect] = field(default_factory=list)
    external_boundaries: list[ExternalBoundary] = field(default_factory=list)
    failures: list[FailurePath] = field(default_factory=list)
    callers: list[RelatedEntity] = field(default_factory=list)
    tests: list[RelatedEntity] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # set only when ref was ambiguous
