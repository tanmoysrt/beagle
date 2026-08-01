from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import RepoError

FETCH_ALL = "+refs/heads/*:refs/heads/*"


@dataclass(frozen=True)
class TreeEntry:
    path: str
    blob_sha: str
    size: int


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    old_path: str | None = None


class Mirror:
    """A bare clone of the reviewed repository.

    Everything reads from here, so reviews never need a checkout and concurrent
    pull requests cannot disturb each other.
    """

    def __init__(self, url: str, path: Path | str, token: str | None = None):
        self.url = url
        self.path = Path(path)
        self.token = token

    @property
    def exists(self) -> bool:
        return (self.path / "HEAD").exists()

    def ensure(self) -> None:
        if self.exists:
            self.fetch()
        else:
            self.clone()

    def clone(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run(["clone", "--mirror", self.url, str(self.path)], in_repo=False)

    def fetch(self, refspec: str = FETCH_ALL) -> None:
        self.run(["fetch", "--prune", "origin", refspec])

    def fetch_pr(self, number: int) -> str:
        """Fetch a pull request head, which may live in a fork, and return its sha."""
        local = f"refs/beagle/pr/{number}"
        self.fetch(f"+refs/pull/{number}/head:{local}")
        return self.resolve(local)

    def resolve(self, ref: str) -> str:
        return self.run(["rev-parse", f"{ref}^{{commit}}"]).strip()

    def has_commit(self, sha: str) -> bool:
        try:
            self.run(["cat-file", "-e", f"{sha}^{{commit}}"])
            return True
        except RepoError:
            return False

    def diff(self, base: str, head: str, context_lines: int = 3) -> str:
        """Diff of what head adds on top of base, the way a pull request reads."""
        return self.run(
            [
                "diff",
                f"--unified={context_lines}",
                "--no-color",
                "--find-renames",
                f"{base}...{head}",
            ]
        )

    def changed_files(self, base: str, head: str) -> list[ChangedFile]:
        raw = self.run(["diff", "--name-status", "--find-renames", "-z", f"{base}...{head}"])
        return parse_name_status(raw)

    def list_tree(self, sha: str) -> list[TreeEntry]:
        raw = self.run(["ls-tree", "-r", "-l", "-z", sha])
        entries = []
        for record in raw.split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            _, kind, blob_sha, size = meta.split(maxsplit=3)
            if kind != "blob":
                continue
            entries.append(TreeEntry(path, blob_sha, int(size.strip()) if size.strip() != "-" else 0))
        return entries

    def read_file(self, sha: str, path: str) -> bytes:
        return self.run_bytes(["show", f"{sha}:{path}"])

    def read_blob(self, blob_sha: str) -> bytes:
        return self.run_bytes(["cat-file", "blob", blob_sha])

    def head_sha(self, branch: str) -> str:
        return self.resolve(branch)

    def run(self, args: list[str], in_repo: bool = True) -> str:
        return self.run_bytes(args, in_repo).decode("utf-8", errors="replace")

    def run_bytes(self, args: list[str], in_repo: bool = True) -> bytes:
        command = ["git"]
        if in_repo:
            command += ["--git-dir", str(self.path)]
        command += self.auth_options() + args
        result = subprocess.run(
            command,
            capture_output=True,
            env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home())},
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RepoError(f"git {' '.join(args[:2])} failed: {detail}")
        return result.stdout

    def auth_options(self) -> list[str]:
        """Pass the token as a header so it never lands in the stored remote URL."""
        if not self.token or self.url.startswith(("git@", "ssh://")):
            return []
        basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        return ["-c", f"http.extraheader=Authorization: Basic {basic}"]


def parse_name_status(raw: str) -> list[ChangedFile]:
    """Read the NUL-separated output of git diff --name-status."""
    fields = [field for field in raw.split("\0") if field]
    changes, index = [], 0
    while index < len(fields):
        status = fields[index]
        if status.startswith("R") or status.startswith("C"):
            changes.append(ChangedFile(fields[index + 2], status[0], old_path=fields[index + 1]))
            index += 3
        else:
            changes.append(ChangedFile(fields[index + 1], status[0]))
            index += 2
    return changes
