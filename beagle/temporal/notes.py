"""Commit-linked metadata via a dedicated Git notes ref (design/13 Phase E).

Episode pointers live under ``refs/notes/beagle-decisions`` so the repository
stays fully usable without beagle and commit messages are never rewritten.
Payloads are small JSON pointers, not full episodes; the episode body stays in
SQLite. Writes are idempotent (``notes add -f``).
"""

from __future__ import annotations

import json
from typing import Optional

from beagle.temporal.git import Git, GitError

NOTES_REF = "refs/notes/beagle-decisions"


class GitNotes:
    def __init__(self, git: Git, ref: str = NOTES_REF):
        self.git = git
        self.ref = ref

    def read(self, sha: str) -> Optional[dict]:
        out = self.git.run("notes", f"--ref={self.ref}", "show", sha, check=False).strip()
        if not out:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"raw": out}

    def write(self, sha: str, payload: dict) -> None:
        self.git.run("notes", f"--ref={self.ref}", "add", "-f",
                     "-m", json.dumps(payload, sort_keys=True), sha)

    def attach_episode(self, sha: str, episode_id: str, changeset) -> None:
        self.write(sha, {
            "episode_id": episode_id,
            "base_commit": getattr(changeset, "base_commit", None),
            "head_commit": getattr(changeset, "head_commit", None),
            "patch_id": getattr(changeset, "patch_id", None),
            "entity_fingerprint": getattr(changeset, "entity_fingerprint", None),
        })
