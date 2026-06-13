"""Read-only Git access for the temporal model.

A thin, explicit wrapper over the ``git`` CLI. It never executes repository
Python and never rewrites history; the only writing operation is attaching a
note under a dedicated ref (see :mod:`beagle.temporal.notes`), kept separate
from these read calls. Commands run with an argument list and no shell, scoped
to the repository root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


class GitError(RuntimeError):
    """A git command failed or git is unavailable."""


class Git:
    def __init__(self, root: Path):
        self.root = Path(root)

    def run(self, *args: str, stdin: Optional[str] = None, check: bool = True) -> str:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(self.root), input=stdin,
                capture_output=True, text=True,
            )
        except FileNotFoundError as exc:  # git not installed
            raise GitError("git executable not found") from exc
        if check and proc.returncode != 0:
            raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
        return proc.stdout

    # --- repository state ---------------------------------------------------

    def is_repo(self) -> bool:
        out = self.run("rev-parse", "--is-inside-work-tree", check=False).strip()
        return out == "true"

    def head(self) -> Optional[str]:
        out = self.run("rev-parse", "HEAD", check=False).strip()
        return out or None

    def branch(self) -> Optional[str]:
        out = self.run("rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
        return out or None

    def rev_parse(self, ref: str) -> Optional[str]:
        out = self.run("rev-parse", "--verify", ref, check=False).strip()
        return out or None

    def is_dirty(self) -> bool:
        return bool(self.run("status", "--porcelain", check=False).strip())

    # --- ranges and commits -------------------------------------------------

    def commits_in_range(self, base: Optional[str], head: str) -> list[str]:
        """Commit shas oldest-first for ``base..head`` (or just ``head``)."""
        spec = f"{base}..{head}" if base else head
        out = self.run("rev-list", "--reverse", spec, check=False)
        return [line for line in out.splitlines() if line]

    def commit_meta(self, sha: str) -> dict:
        fmt = "%P%n%an <%ae>%n%at%n%s"
        out = self.run("show", "-s", f"--format={fmt}", sha)
        parents, author, ts, *subject = out.splitlines()
        return {
            "parents": parents.split() if parents else [],
            "author": author,
            "timestamp": float(ts) if ts else 0.0,
            "message": subject[0] if subject else "",
        }

    # --- diffs --------------------------------------------------------------

    def diff_commit(self, sha: str) -> str:
        """Unified diff a commit introduces against its parent."""
        return self.run("show", "-U0", "--format=", sha, check=False)

    def diff_range(self, base: Optional[str], head: str) -> str:
        args = ["diff", "-U0", f"{base}..{head}"] if base else ["show", "-U0", "--format=", head]
        return self.run(*args, check=False)

    def diff_working(self) -> str:
        """Tracked changes in the working tree and index against HEAD."""
        return self.run("diff", "-U0", "HEAD", check=False)

    def patch_id(self, diff_text: str) -> Optional[str]:
        if not diff_text.strip():
            return None
        out = self.run("patch-id", "--stable", stdin=diff_text, check=False).strip()
        return out.split()[0] if out else None
