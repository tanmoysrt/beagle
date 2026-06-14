"""Read and parse commit metadata from a bare mirror (design/15 §9, §10 Tier 0).

A single ``git log`` call over all reachable refs yields every commit's full
metadata, message body, parents, signature status, and diff statistics. Parsing
is deterministic and preserves the original Git fields exactly — author and
committer identities are kept separate, and trailers are evidence, not verified
mappings.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from beagle.service.config import ServiceConfig
from beagle.service.errors import ServiceError

_RS = "\x1e"  # record separator between commits
_US = "\x1f"  # unit separator between fields
_FIELDS = ["%H", "%T", "%P", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%G?", "%s", "%b"]
# Trailing %x1f isolates the --shortstat block as the final split element.
_FORMAT = _RS + _US.join(_FIELDS) + _US

_SHORTSTAT = re.compile(
    r"(\d+) files? changed"
    r"(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)
_TRAILER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*): (.+)$")


@dataclass
class ParsedCommit:
    sha: str
    tree_sha: str
    parents: list[str]
    author_name: str
    author_email: str
    author_time: int
    author_tz: str
    committer_name: str
    committer_email: str
    commit_time: int
    committer_tz: str
    signature_status: str
    subject: str
    body: str
    trailers: list[tuple[str, str]] = field(default_factory=list)
    files_changed: int | None = None
    insertions: int | None = None
    deletions: int | None = None

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


class CommitReader:
    """Reads every reachable commit from a bare repository."""

    def __init__(self, config: ServiceConfig):
        self._git = config.git_binary

    def read(self, repo_path: Path) -> list[ParsedCommit]:
        result = subprocess.run(
            [self._git, "log", "--all", "--shortstat", "--no-color", f"--format={_FORMAT}"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ServiceError(f"git log failed: {result.stderr.strip()}")
        return [
            self._parse(chunk)
            for chunk in result.stdout.split(_RS)
            if chunk.strip()
        ]

    def _parse(self, chunk: str) -> ParsedCommit:
        fields = chunk.split(_US)
        author_time, author_tz = _epoch_tz(fields[5])
        commit_time, committer_tz = _epoch_tz(fields[8])
        body = fields[11].strip("\n")
        files_changed, insertions, deletions = _parse_shortstat(
            fields[12] if len(fields) > 12 else ""
        )
        return ParsedCommit(
            sha=fields[0],
            tree_sha=fields[1],
            parents=fields[2].split(),
            author_name=fields[3],
            author_email=fields[4],
            author_time=author_time,
            author_tz=author_tz,
            committer_name=fields[6],
            committer_email=fields[7],
            commit_time=commit_time,
            committer_tz=committer_tz,
            signature_status=fields[9] or "N",
            subject=fields[10],
            body=body,
            trailers=_parse_trailers(body),
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
        )


def _epoch_tz(iso: str) -> tuple[int, str]:
    moment = datetime.fromisoformat(iso)
    return int(moment.timestamp()), moment.strftime("%z")


def _parse_shortstat(text: str) -> tuple[int | None, int | None, int | None]:
    match = _SHORTSTAT.search(text)
    if not match:
        return None, None, None
    files, insertions, deletions = match.groups()
    return int(files), int(insertions or 0), int(deletions or 0)


def _parse_trailers(body: str) -> list[tuple[str, str]]:
    """Collect the trailing block of ``Key: value`` lines (git trailer convention)."""
    collected: list[tuple[str, str]] = []
    for line in reversed(body.splitlines()):
        if not line.strip():
            if collected:
                break
            continue
        match = _TRAILER.match(line.strip())
        if not match:
            break
        collected.append((match.group(1), match.group(2).strip()))
    return list(reversed(collected))
