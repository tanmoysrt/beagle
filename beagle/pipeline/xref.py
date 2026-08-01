from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..repo.diff import FileDiff
from ..repo.mirror import Mirror

log = logging.getLogger("beagle.pipeline.xref")

MAX_NAMES = 12
MAX_HITS_PER_NAME = 6
MAX_HITS_TOTAL = 30
MIN_NAME_LENGTH = 5

DEFINITION = re.compile(
    r"^[-+]\s*(?:export\s+)?(?:async\s+)?"
    r"(?:def|class|function|const|let|var|interface|type|struct|func)\s+([A-Za-z_][\w]*)"
)
DECORATED_ROUTE = re.compile(r"""^[-+].*?['"](/[A-Za-z0-9_./{}:-]{4,})['"]""")
DOTTED_PATH = re.compile(r"""['"]([a-z][\w]*(?:\.[\w]+){2,})['"]""")

LANGUAGE_OF = {
    ".py": "python", ".pyi": "python",
    ".js": "web", ".jsx": "web", ".ts": "web", ".tsx": "web", ".mjs": "web", ".vue": "web",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".java": "java",
}


@dataclass(frozen=True)
class Reference:
    name: str
    path: str
    line: int
    text: str


class CrossReferences:
    """Finds the rest of the codebase that names what this diff removed or renamed.

    The call graph misses a Vue component that reaches a Python endpoint by its
    route string. A literal search over the whole tree finds it, and costs no tokens.
    """

    def __init__(self, mirror: Mirror):
        self.mirror = mirror

    def find(self, diffs: list[FileDiff], head_sha: str | None) -> list[Reference]:
        if not head_sha:
            return []
        own = {item.path for item in diffs} | {item.old_path for item in diffs if item.old_path}
        names = self.names_at_risk(diffs)
        found: list[Reference] = []
        for name in names[:MAX_NAMES]:
            found.extend(self.search(name, head_sha, own))
            if len(found) >= MAX_HITS_TOTAL:
                break
        return self.rank(found, diffs)[:MAX_HITS_TOTAL]

    def names_at_risk(self, diffs: list[FileDiff]) -> list[str]:
        removed: dict[str, int] = {}
        added: set[str] = set()
        for file_diff in diffs:
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind not in ("-", "+"):
                        continue
                    for name in candidates(line.kind + line.text):
                        if line.kind == "-":
                            removed[name] = removed.get(name, 0) + 1
                        else:
                            added.add(name)
        # a name the diff also adds back is still served
        return [name for name in removed if name not in added]

    def search(self, name: str, head_sha: str, own: set[str]) -> list[Reference]:
        try:
            raw = self.mirror.run(
                ["grep", "-n", "--fixed-strings", "-I", "-e", name, head_sha]
            )
        except Exception as exc:
            log.debug("cross reference search for %s failed: %s", name, exc)
            return []
        hits = []
        for row in raw.splitlines():
            hit = parse_grep_line(row, head_sha, name)
            if hit is None or hit.path in own:
                continue
            hits.append(hit)
            if len(hits) >= MAX_HITS_PER_NAME:
                break
        return hits

    def rank(self, hits: list[Reference], diffs: list[FileDiff]) -> list[Reference]:
        """Another language first: that is the caller a reviewer will not think to check."""
        changed = {language_of(item.path) for item in diffs}
        return sorted(hits, key=lambda hit: (language_of(hit.path) in changed, hit.path, hit.line))


def render(hits: list[Reference]) -> str:
    if not hits:
        return ""
    lines = []
    for hit in hits:
        lines.append(f"{hit.path}:{hit.line} uses `{hit.name}` — {hit.text[:160]}")
    return "\n".join(lines)


def candidates(line: str) -> list[str]:
    names = []
    found = DEFINITION.match(line)
    if found:
        names.append(found.group(1))
    route = DECORATED_ROUTE.match(line)
    if route:
        names.append(route.group(1))
    names.extend(DOTTED_PATH.findall(line))
    return [name for name in names if len(name) >= MIN_NAME_LENGTH and not name.startswith("_")]


def parse_grep_line(row: str, head_sha: str, name: str) -> Reference | None:
    """`git grep` on a commit prefixes each hit with `<sha>:<path>:<line>:`."""
    body = row[len(head_sha) + 1:] if row.startswith(f"{head_sha}:") else row
    parts = body.split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return Reference(name=name, path=parts[0], line=int(parts[1]), text=parts[2].strip())


def language_of(path: str) -> str:
    suffix = path[path.rfind("."):] if "." in path else ""
    return LANGUAGE_OF.get(suffix, "other")
