"""Local Git state for the bridge (design/15 §7).

Reads the working repository without modifying it: current HEAD and branch,
dirty-tree detection, and a patch overlay of uncommitted tracked changes. Used to
decide what (if anything) must be synchronized to the service.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from beagle.service.errors import ServiceError


class LocalRepository:
    """A working repository on the developer's machine."""

    def __init__(self, root: Path, git_binary: str = "git"):
        self.root = root
        self._git = git_binary

    def head_sha(self) -> str:
        return self._run(["rev-parse", "HEAD"]).strip()

    def branch(self) -> str:
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def is_dirty(self) -> bool:
        return bool(self._run(["status", "--porcelain"]).strip())

    def dirty_patch(self) -> str:
        """Unified diff of uncommitted tracked changes (empty if clean)."""
        return self._run(["diff", "HEAD"])

    def dirty_fingerprint(self) -> str:
        status = self._run(["status", "--porcelain"])
        patch = self.dirty_patch()
        return hashlib.sha256((status + patch).encode()).hexdigest()

    def _run(self, args: list[str]) -> str:
        result = subprocess.run(
            [self._git, *args], cwd=str(self.root), capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ServiceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout
