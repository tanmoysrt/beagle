from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..constants import MAX_FILE_BYTES
from .mirror import Mirror, TreeEntry

BEAGLEIGNORE = ".beagleignore"

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".vue": "vue",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".pdf",
    ".zip", ".gz", ".bz2", ".xz", ".7z", ".tar", ".jar", ".war", ".class",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".wasm", ".o", ".a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi",
    ".pyc", ".pyd", ".db", ".sqlite", ".parquet", ".pkl", ".npy",
}


@dataclass(frozen=True)
class SelectedFile:
    path: str
    blob_sha: str
    size: int
    lang: str | None


@dataclass(frozen=True)
class SkippedFile:
    path: str
    reason: str


@dataclass
class Selection:
    files: list[SelectedFile] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)

    @property
    def paths(self) -> set[str]:
        return {file.path for file in self.files}


class FileSelector:
    """Decides what Beagle may look at. Anything absent from the tree is already
    gitignored, leaving .beagleignore, operator globs, and size or binary limits."""

    def __init__(self, mirror: Mirror, ignore_globs: list[str] | None = None, max_bytes: int = MAX_FILE_BYTES):
        self.mirror = mirror
        self.ignore_globs = list(ignore_globs or [])
        self.max_bytes = max_bytes

    def select(self, sha: str) -> Selection:
        entries = self.mirror.list_tree(sha)
        return self.apply_rules(sha, entries)

    def select_paths(self, sha: str, paths: list[str]) -> Selection:
        """Same rules, restricted to the paths a diff touched."""
        wanted = set(paths)
        entries = [entry for entry in self.mirror.list_tree(sha) if entry.path in wanted]
        selection = self.apply_rules(sha, entries)
        found = selection.paths | {skip.path for skip in selection.skipped}
        for missing in wanted - found:
            selection.skipped.append(SkippedFile(missing, "not present at this revision"))
        return selection

    def apply_rules(self, sha: str, entries: list[TreeEntry]) -> Selection:
        ignored = self.ignored_paths(sha, [entry.path for entry in entries])
        selection = Selection()
        for entry in entries:
            reason = ignored.get(entry.path) or self.limit_reason(entry)
            if reason:
                selection.skipped.append(SkippedFile(entry.path, reason))
            else:
                selection.files.append(
                    SelectedFile(entry.path, entry.blob_sha, entry.size, language_of(entry.path))
                )
        return selection

    def limit_reason(self, entry: TreeEntry) -> str | None:
        if Path(entry.path).suffix.lower() in BINARY_SUFFIXES:
            return "binary file"
        if entry.size > self.max_bytes:
            return f"larger than {self.max_bytes // 1024} KB"
        if entry.size == 0:
            return "empty file"
        return None

    def ignored_paths(self, sha: str, paths: list[str]) -> dict[str, str]:
        """Ask git itself which paths the ignore rules match, and why."""
        rules = self.collect_rules(sha)
        if not rules or not paths:
            return {}
        with tempfile.TemporaryDirectory() as workspace:
            excludes = Path(workspace) / "excludes"
            excludes.write_text("\n".join(rules) + "\n", encoding="utf-8")
            worktree = Path(workspace) / "empty"
            worktree.mkdir()
            result = subprocess.run(
                [
                    "git",
                    "--git-dir", str(self.mirror.path),
                    "--work-tree", str(worktree),
                    "-c", f"core.excludesFile={excludes}",
                    "check-ignore", "--no-index", "--stdin", "-v",
                ],
                input="\n".join(paths),
                capture_output=True,
                text=True,
            )
        return parse_check_ignore(result.stdout)

    def collect_rules(self, sha: str) -> list[str]:
        rules = []
        try:
            content = self.mirror.read_file(sha, BEAGLEIGNORE).decode("utf-8", errors="replace")
            rules.extend(line for line in content.splitlines() if line.strip())
        except Exception:
            pass  # no .beagleignore in this revision
        rules.extend(self.ignore_globs)
        return rules


def parse_check_ignore(output: str) -> dict[str, str]:
    matches = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        source, _, path = line.rpartition("\t")
        parts = source.split(":")
        rule = parts[-1] if parts else source
        matches[path] = f"ignored by rule '{rule}'"
    return matches


def language_of(path: str) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower())


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]
