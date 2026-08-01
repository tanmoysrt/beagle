from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..repo.mirror import Mirror

CHARS_PER_TOKEN = 4
MAX_FILE_CHARS = 24000

# Names teams already use for rules aimed at humans and AI tools alike.
STRONG_NAMES = {
    "claude.md": 10,
    "agents.md": 10,
    "agent.md": 9,
    ".cursorrules": 9,
    "copilot-instructions.md": 9,
    "conventions.md": 8,
    "contributing.md": 8,
    "contributing": 7,
    "style.md": 8,
    "styleguide.md": 8,
    "style-guide.md": 8,
    "architecture.md": 7,
    "spec.md": 7,
    "code_review.md": 8,
    "code-review.md": 8,
    "engineering.md": 6,
    "standards.md": 7,
}

FUZZY_TERMS = (
    ("convention", 6),
    ("guideline", 6),
    ("style", 5),
    ("standard", 5),
    ("handbook", 5),
    ("contributing", 6),
    ("architecture", 4),
    ("spec", 4),
    ("review", 4),
    ("instruction", 6),
)

SKIP_DIRS = ("node_modules/", "vendor/", "third_party/", ".github/workflows/")
TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".rst", "")


@dataclass
class InstructionFile:
    path: str
    score: float
    text: str

    @property
    def directory(self) -> str:
        parent = str(PurePosixPath(self.path).parent)
        return "" if parent == "." else parent

    def applies_to(self, paths: list[str]) -> bool:
        """A nested rules file governs its own subtree only."""
        if not self.directory:
            return True
        return any(path.startswith(f"{self.directory}/") for path in paths)


class InstructionFinder:
    """Finds the repository's own rules files by fuzzy name scoring."""

    def __init__(self, mirror: Mirror, extra: list[str] | None = None):
        self.mirror = mirror
        self.extra = list(extra or [])

    def discover(self, sha: str, tracked: list[str]) -> list[InstructionFile]:
        candidates = []
        for path in tracked:
            score = score_path(path)
            if path in self.extra:
                score = max(score, 12)
            if score > 0:
                candidates.append((score, path))
        candidates.sort(key=lambda pair: (-pair[0], pair[1]))

        found = []
        for score, path in candidates:
            text = self.read(sha, path)
            if text:
                found.append(InstructionFile(path, score, text))
        return found

    def read(self, sha: str, path: str) -> str:
        try:
            raw = self.mirror.read_file(sha, path).decode("utf-8", errors="replace")
        except Exception:
            return ""
        return raw[:MAX_FILE_CHARS].strip()

    def block(
        self, files: list[InstructionFile], unit_paths: list[str], budget_tokens: int
    ) -> tuple[str, list[str]]:
        """Render the applicable files, highest scoring first, within budget."""
        if not files or budget_tokens <= 0:
            return "", []
        applicable = [item for item in files if item.applies_to(unit_paths)]
        sections, applied, used = [], [], 0
        for item in applicable:
            cost = len(item.text) // CHARS_PER_TOKEN
            if used + cost > budget_tokens:
                remaining = (budget_tokens - used) * CHARS_PER_TOKEN
                if remaining < 400:
                    break
                trimmed = item.text[:remaining].rstrip()
                sections.append(section(item.path, trimmed + "\n…(truncated)"))
                applied.append(item.path)
                break
            sections.append(section(item.path, item.text))
            applied.append(item.path)
            used += cost
        if not sections:
            return "", []
        header = "REPOSITORY INSTRUCTION FILES — these are law for this review:\n\n"
        return header + "\n\n".join(sections), applied


def section(path: str, text: str) -> str:
    return f"--- {path} ---\n{text}"


def score_path(path: str) -> float:
    if any(skip in path for skip in SKIP_DIRS):
        return 0
    name = PurePosixPath(path).name.lower()
    if PurePosixPath(name).suffix not in TEXT_SUFFIXES:
        return 0

    score = STRONG_NAMES.get(name, 0)
    if not score:
        stem = re.sub(r"[^a-z]+", " ", PurePosixPath(name).stem.lower())
        for term, weight in FUZZY_TERMS:
            if term in stem:
                score = max(score, weight)
    if not score:
        return 0

    depth = path.count("/")
    if depth == 0:
        score += 3
    elif path.startswith("docs/") or path.startswith(".github/"):
        score += 1
    score -= min(depth, 4) * 0.5
    return score
