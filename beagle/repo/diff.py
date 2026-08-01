from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass(frozen=True)
class DiffLine:
    kind: str
    text: str
    old_line: int | None
    new_line: int | None


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    heading: str
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def header(self) -> str:
        return f"@@ -{self.old_start},{self.old_count} +{self.new_start},{self.new_count} @@{self.heading}"


@dataclass
class FileDiff:
    path: str
    old_path: str | None = None
    status: str = "M"
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[tuple[int, str]]:
        """New lines with their line numbers, for scanners that only care about additions."""
        return [
            (line.new_line, line.text)
            for hunk in self.hunks
            for line in hunk.lines
            if line.kind == "+" and line.new_line is not None
        ]

    @property
    def added_count(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines if line.kind == "+")

    @property
    def removed_count(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines if line.kind == "-")

    @property
    def changed_line_ranges(self) -> list[tuple[int, int]]:
        ranges = []
        for hunk in self.hunks:
            numbers = [line.new_line for line in hunk.lines if line.kind == "+" and line.new_line]
            if numbers:
                ranges.append((min(numbers), max(numbers)))
        return ranges

    def render(self, collapse_deletions: bool = True, max_run: int = 3) -> str:
        """Diff text for a prompt, with long deletion runs folded into markers."""
        out = [f"--- {self.old_path or self.path}", f"+++ {self.path}"]
        if self.binary:
            return "\n".join(out + ["(binary file, not reviewed)"])
        for hunk in self.hunks:
            out.append(hunk.header)
            out.extend(render_hunk_lines(hunk, collapse_deletions, max_run))
        return "\n".join(out)


def parse_diff(text: str) -> list[FileDiff]:
    """Parse unified diff output, whether git produced it or a client posted it."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_line = new_line = 0

    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = start_file(line)
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif line.startswith("new file mode"):
            current.status = "A"
        elif line.startswith("deleted file mode"):
            current.status = "D"
        elif line.startswith("rename from "):
            current.old_path = line[len("rename from ") :].strip()
            current.status = "R"
        elif line.startswith("rename to "):
            current.path = line[len("rename to ") :].strip()
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.binary = True
        elif line.startswith("--- "):
            current.old_path = strip_prefix(line[4:]) or current.old_path
        elif line.startswith("+++ "):
            path = strip_prefix(line[4:])
            if path:
                current.path = path
        elif line.startswith("@@"):
            match = HUNK_HEADER.match(line)
            if not match:
                continue
            old_start, old_count, new_start, new_count, heading = match.groups()
            hunk = Hunk(
                int(old_start), int(old_count or 1), int(new_start), int(new_count or 1), heading
            )
            current.hunks.append(hunk)
            old_line, new_line = hunk.old_start, hunk.new_start
        elif hunk is not None and line[:1] in ("+", "-", " ", ""):
            kind = line[:1] or " "
            body = line[1:]
            if kind == "+":
                hunk.lines.append(DiffLine("+", body, None, new_line))
                new_line += 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", body, old_line, None))
                old_line += 1
            else:
                hunk.lines.append(DiffLine(" ", body, old_line, new_line))
                old_line += 1
                new_line += 1
    return files


def start_file(header: str) -> FileDiff:
    parts = header.split(" b/", 1)
    path = parts[1].strip() if len(parts) == 2 else header.split()[-1]
    old = parts[0].split(" a/", 1)
    old_path = old[1].strip() if len(old) == 2 else None
    return FileDiff(path=path, old_path=old_path)


def strip_prefix(path: str) -> str | None:
    path = path.strip()
    if path == "/dev/null":
        return None
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def render_hunk_lines(hunk: Hunk, collapse_deletions: bool, max_run: int) -> list[str]:
    rendered, run = [], []
    for line in hunk.lines:
        if collapse_deletions and line.kind == "-":
            run.append(line)
            continue
        rendered.extend(flush_deletions(run, max_run))
        run = []
        prefix = line.kind
        rendered.append(f"{prefix}{line.text}")
    rendered.extend(flush_deletions(run, max_run))
    return rendered


def flush_deletions(run: list[DiffLine], max_run: int) -> list[str]:
    if not run:
        return []
    if len(run) <= max_run:
        return [f"-{line.text}" for line in run]
    return [f"-{run[0].text}", f"- … {len(run) - 2} more deleted lines …", f"-{run[-1].text}"]
