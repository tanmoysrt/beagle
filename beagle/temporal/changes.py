"""Deterministic Git-change model (design/13 Phase A).

Parses a unified diff into per-file deltas, then maps changed line ranges to
beagle entities using the current index. Mapping is exact for the working tree
and the indexed HEAD; for older revisions the indexed ranges may not match, so
those changes are reported at path level with a note rather than guessed. No
LLM, no behaviour inference beyond what the diff and the index prove.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from beagle.database.repository import Repository
from beagle.temporal.models import ChangeSet, EntityChange

_CODE_KINDS = ("function", "method", "test_function", "class", "test_class")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileDelta:
    status: str                       # added | removed | renamed | modified
    path_before: Optional[str]
    path_after: Optional[str]
    new_ranges: list[tuple[int, int]] = field(default_factory=list)
    old_ranges: list[tuple[int, int]] = field(default_factory=list)


def parse_diff(text: str) -> list[FileDelta]:
    """Split a ``git diff`` (any -U context) into per-file deltas."""
    deltas: list[FileDelta] = []
    current: Optional[FileDelta] = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = FileDelta("modified", None, None)
            deltas.append(current)
        elif current is None:
            continue
        elif line.startswith("rename from "):
            current.status, current.path_before = "renamed", line[12:].strip()
        elif line.startswith("rename to "):
            current.path_after = line[10:].strip()
        elif line.startswith("new file"):
            current.status = "added"
        elif line.startswith("deleted file"):
            current.status = "removed"
        elif line.startswith("--- "):
            current.path_before = _path(line[4:], current.path_before)
        elif line.startswith("+++ "):
            current.path_after = _path(line[4:], current.path_after)
        elif line.startswith("@@"):
            _add_hunk(current, line)
    return deltas


def _path(token: str, fallback: Optional[str]) -> Optional[str]:
    token = token.strip()
    if token == "/dev/null":
        return None
    return token[2:] if token[:2] in ("a/", "b/") else token or fallback


def _add_hunk(delta: FileDelta, line: str) -> None:
    m = _HUNK.match(line)
    if not m:
        return
    old_start, old_len, new_start, new_len = (int(m.group(i) or 1) for i in (1, 2, 3, 4))
    if new_len:
        delta.new_ranges.append((new_start, new_start + new_len - 1))
    if old_len:
        delta.old_ranges.append((old_start, old_start + old_len - 1))


class ChangeAnalyzer:
    """Maps file deltas to :class:`EntityChange` records via the index."""

    def __init__(self, repo: Repository, indexed_head: bool = True):
        self.repo = repo
        self.indexed_head = indexed_head  # post-image matches the current index

    def entity_changes(self, deltas: list[FileDelta]) -> list[EntityChange]:
        changes: list[EntityChange] = []
        for delta in deltas:
            changes.extend(self._delta_changes(delta))
        return changes

    def _delta_changes(self, delta: FileDelta) -> list[EntityChange]:
        if delta.status == "removed":
            return [EntityChange("removed", path_before=delta.path_before, confidence=1.0)]
        if delta.status == "added":
            return self._whole_file(delta, "added")
        return self._modified(delta)

    def _whole_file(self, delta: FileDelta, change_type: str) -> list[EntityChange]:
        entities = self.repo.entities_in_file(delta.path_after or "", _CODE_KINDS)
        if not entities:
            return [EntityChange(change_type, path_after=delta.path_after)]
        return [
            EntityChange(change_type, entity_after=e.id,
                         path_after=delta.path_after, diff_ranges=delta.new_ranges)
            for e in entities
        ]

    def _modified(self, delta: FileDelta) -> list[EntityChange]:
        path = delta.path_after or delta.path_before
        renamed = delta.status == "renamed"
        if not self.indexed_head:
            return [self._path_level(delta, renamed)]
        touched: dict[str, EntityChange] = {}
        for line in _lines(delta.new_ranges):
            entity = self.repo.entity_containing(path, line, _CODE_KINDS)
            if entity is None:
                continue
            change = touched.setdefault(entity.id, EntityChange(
                "renamed" if renamed else "modified",
                entity_before=entity.id, entity_after=entity.id,
                path_before=delta.path_before, path_after=delta.path_after))
            if line == entity.source_range.start_line and not renamed:
                change.change_type = "signature_changed"
            change.diff_ranges.append((line, line))
        return list(touched.values()) or [self._path_level(delta, renamed)]

    def _path_level(self, delta: FileDelta, renamed: bool) -> EntityChange:
        return EntityChange(
            "renamed" if renamed else "modified",
            path_before=delta.path_before, path_after=delta.path_after,
            diff_ranges=delta.new_ranges, confidence=0.5,
        )


def _lines(ranges: list[tuple[int, int]]) -> list[int]:
    out: list[int] = []
    for start, end in ranges:
        out.extend(range(start, end + 1))
    return out


def entity_fingerprint(changes: list[EntityChange]) -> str:
    """Stable hash over (entity, change_type, path) — survives rebases."""
    parts = sorted(
        f"{c.entity_after or c.entity_before or c.path_after or c.path_before}"
        f"|{c.change_type}"
        for c in changes
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def changeset(base: Optional[str], head: Optional[str], patch_id: Optional[str],
              changes: list[EntityChange]) -> ChangeSet:
    cid = f"changeset-{(patch_id or entity_fingerprint(changes))[:12]}"
    return ChangeSet(cid, base, head, patch_id, entity_fingerprint(changes),
                     summary=_summary(changes))


def _summary(changes: list[EntityChange]) -> str:
    counts: dict[str, int] = {}
    for c in changes:
        counts[c.change_type] = counts.get(c.change_type, 0) + 1
    return ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
