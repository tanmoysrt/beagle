"""Bare Git mirror management (design/15 §6, §7).

Wraps the ``git`` CLI to keep one bare repository per registered repository id.
The mirror never executes repository code: it only moves Git objects and reads
metadata. Upstream history is fetched into the canonical Beagle namespace; a
``pre-receive`` hook enforces per-user push scoping.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from beagle.service.config import ServiceConfig
from beagle.service.errors import NotFound, ServiceError
from beagle.service.git import refs

_PRE_RECEIVE_HOOK = """#!/bin/sh
# Installed by Beagle. Rejects pushes outside the pushing user's namespace.
user="${BEAGLE_PUSH_USER:-}"
rc=0
while read -r old new ref; do
    case "$ref" in
        refs/beagle/users/"$user"/*) ;;
        refs/beagle/workspaces/"$user"/*) ;;
        *)
            echo "beagle: push to '$ref' denied for user '${user:-<none>}'" >&2
            rc=1
            ;;
    esac
done
exit $rc
"""


@dataclass
class RefEntry:
    ref_name: str
    commit_sha: str


class GitMirror:
    """Owns the bare repositories under the configured storage root."""

    def __init__(self, config: ServiceConfig):
        self._git = config.git_binary
        self._root = config.repo_storage_root

    def path_for(self, repository_id: str) -> Path:
        return self._root / f"{repository_id}.git"

    def init_bare(self, repository_id: str) -> Path:
        path = self.path_for(repository_id)
        path.mkdir(parents=True, exist_ok=True)
        self._run(["init", "--bare", "--quiet"], cwd=path)
        self._install_hook(path)
        return path

    def set_upstream(self, repository_id: str, remote_url: str) -> None:
        path = self._require(repository_id)
        self._run(["remote", "remove", "upstream"], cwd=path, check=False)
        self._run(["remote", "add", "upstream", remote_url], cwd=path)
        # Drop the auto-created +refs/heads/*:refs/remotes/upstream/* refspec so
        # only the canonical Beagle namespace is ever populated.
        self._run(["config", "--unset-all", "remote.upstream.fetch"], cwd=path, check=False)
        for refspec in refs.UPSTREAM_FETCH_REFSPECS:
            self._run(
                ["config", "--add", "remote.upstream.fetch", refspec], cwd=path
            )

    def fetch_upstream(self, repository_id: str) -> list[RefEntry]:
        path = self._require(repository_id)
        self._run(["fetch", "--prune", "--quiet", "upstream"], cwd=path)
        return self.list_refs(repository_id, prefix="refs/beagle/upstream/")

    def list_refs(self, repository_id: str, prefix: str | None = None) -> list[RefEntry]:
        path = self._require(repository_id)
        args = ["for-each-ref", "--format=%(refname) %(objectname)"]
        if prefix:
            args.append(prefix)
        output = self._run(args, cwd=path).stdout.strip()
        entries = []
        for line in output.splitlines():
            name, _, sha = line.partition(" ")
            if name and sha:
                entries.append(RefEntry(name, sha))
        return entries

    def resolve(self, repository_id: str, revision: str) -> str | None:
        path = self._require(repository_id)
        result = self._run(
            ["rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
            cwd=path,
            check=False,
        )
        sha = result.stdout.strip()
        return sha or None

    def has_commit(self, repository_id: str, sha: str) -> bool:
        path = self._require(repository_id)
        result = self._run(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=path, check=False)
        return result.returncode == 0

    def tree_sha(self, repository_id: str, revision: str) -> str | None:
        path = self._require(repository_id)
        result = self._run(
            ["rev-parse", "--verify", "--quiet", f"{revision}^{{tree}}"],
            cwd=path,
            check=False,
        )
        return result.stdout.strip() or None

    def rev_list(self, repository_id: str, revision: str, limit: int) -> list[str]:
        """Return commit SHAs reachable from ``revision``, parent-first."""
        path = self._require(repository_id)
        result = self._run(
            ["rev-list", "--reverse", "--topo-order", f"--max-count={limit}", revision],
            cwd=path,
            check=False,
        )
        return [line for line in result.stdout.split() if line]

    def merge_base(self, repository_id: str, a: str, b: str) -> str | None:
        path = self._require(repository_id)
        result = self._run(["merge-base", a, b], cwd=path, check=False)
        return result.stdout.strip() or None

    def diff_name_status(
        self, repository_id: str, base: str, head: str
    ) -> list[tuple[str, str]]:
        path = self._require(repository_id)
        result = self._run(["diff", "--name-status", base, head], cwd=path)
        changes = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changes.append((parts[0], parts[-1]))
        return changes

    def commits_between(
        self, repository_id: str, base: str, head: str, limit: int = 200
    ) -> list[str]:
        """SHAs reachable from ``head`` but not ``base`` (newest first)."""
        path = self._require(repository_id)
        result = self._run(
            ["rev-list", f"--max-count={limit}", f"{base}..{head}"], cwd=path, check=False
        )
        return [line for line in result.stdout.split() if line]

    def read_file(self, repository_id: str, revision: str, path: str) -> bytes | None:
        """Return a tracked file's bytes at ``revision``, or None if absent."""
        repo = self._require(repository_id)
        result = subprocess.run(
            [self._git, "show", f"{revision}:{path}"],
            cwd=str(repo), capture_output=True,
        )
        return result.stdout if result.returncode == 0 else None

    def export_tree(self, repository_id: str, revision: str, dest: Path) -> None:
        """Materialize a commit's tree into ``dest`` (tracked files only, no .git)."""
        path = self._require(repository_id)
        archive = self._run_bytes(["archive", "--format=tar", revision], cwd=path)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            members = [m for m in tar.getmembers() if _is_safe_member(m, dest)]
            tar.extractall(dest, members=members)

    def verify_integrity(self, repository_id: str) -> None:
        """Run ``git fsck``; raise :class:`ServiceError` on corruption."""
        path = self._require(repository_id)
        result = self._run(
            ["fsck", "--connectivity-only", "--no-progress"], cwd=path, check=False
        )
        if result.returncode != 0:
            raise ServiceError(f"integrity check failed: {result.stderr.strip()}")

    def _require(self, repository_id: str) -> Path:
        path = self.path_for(repository_id)
        if not path.exists():
            raise NotFound(f"repository mirror not found: {repository_id}")
        return path

    def _install_hook(self, path: Path) -> None:
        hook = path / "hooks" / "pre-receive"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(_PRE_RECEIVE_HOOK)
        hook.chmod(0o755)

    def _run(
        self, args: list[str], cwd: Path, check: bool = True
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [self._git, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise ServiceError(
                f"git {' '.join(args)} failed: {result.stderr.strip()}"
            )
        return result

    def _run_bytes(self, args: list[str], cwd: Path) -> bytes:
        result = subprocess.run([self._git, *args], cwd=str(cwd), capture_output=True)
        if result.returncode != 0:
            raise ServiceError(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")
        return result.stdout


def _is_safe_member(member: tarfile.TarInfo, dest: Path) -> bool:
    """Reject path traversal and unsafe symlinks in an exported tree."""
    if member.issym() or member.islnk():
        return False
    target = (dest / member.name).resolve()
    return dest.resolve() in target.parents or target == dest.resolve()
