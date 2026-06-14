"""Revision comparison (design/15 §19).

Compares two revisions and returns changed files, changed entities, the commit
range, and the authors/committers involved — all keyed to exact commits. Branch
comparison reports source and target changes separately around the merge base;
a merge summary analyzes the merge result tree, not the union of parent diffs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from beagle.database import Database as EngineDatabase
from beagle.database.repository import Repository as EngineRepository
from beagle.service.commit_store import CommitStore
from beagle.service.db import Database
from beagle.service.errors import NotFound
from beagle.service.git.mirror import GitMirror
from beagle.service.revision_indexer import RevisionIndexer


@dataclass
class ComparisonResult:
    repository_id: str
    base_commit: str
    head_commit: str
    changed_files: list[dict] = field(default_factory=list)
    entities_added: list[dict] = field(default_factory=list)
    entities_removed: list[dict] = field(default_factory=list)
    entities_changed: list[dict] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)


@dataclass
class BranchComparison:
    repository_id: str
    merge_base: str | None
    source: ComparisonResult
    target: ComparisonResult


class RevisionComparer:
    """Compares revisions and branches using indexed snapshots and commits."""

    def __init__(
        self,
        database: Database,
        mirror: GitMirror,
        indexer: RevisionIndexer,
        commits: CommitStore,
    ):
        self._db = database
        self._mirror = mirror
        self._indexer = indexer
        self._commits = commits

    def compare(self, repository_id: str, base: str, head: str) -> ComparisonResult:
        base_sha = self._resolve(repository_id, base)
        head_sha = self._resolve(repository_id, head)
        base_snap = self._indexer.index_revision(repository_id, base_sha)
        head_snap = self._indexer.index_revision(repository_id, head_sha)
        result = ComparisonResult(repository_id, base_sha, head_sha)
        result.changed_files = [
            {"status": status, "path": path}
            for status, path in self._mirror.diff_name_status(repository_id, base_sha, head_sha)
        ]
        self._diff_entities(base_snap.artifact_path, head_snap.artifact_path, result)
        self._collect_commits(repository_id, base_sha, head_sha, result)
        return result

    def branch_compare(
        self, repository_id: str, target: str, source: str
    ) -> BranchComparison:
        """Compare a source branch against a target around their merge base."""
        target_sha = self._resolve(repository_id, target)
        source_sha = self._resolve(repository_id, source)
        base = self._mirror.merge_base(repository_id, target_sha, source_sha)
        if not base:
            raise NotFound("no merge base between revisions")
        return BranchComparison(
            repository_id=repository_id,
            merge_base=base,
            source=self.compare(repository_id, base, source_sha),
            target=self.compare(repository_id, base, target_sha),
        )

    def merge_summary(self, repository_id: str, merge_revision: str) -> ComparisonResult:
        """Summarize a merge by diffing its first parent against the merge tree."""
        merge_sha = self._resolve(repository_id, merge_revision)
        first_parent = self._mirror.resolve(repository_id, f"{merge_sha}^1")
        if not first_parent:
            raise NotFound("revision is not a merge commit")
        return self.compare(repository_id, first_parent, merge_sha)

    def _resolve(self, repository_id: str, revision: str) -> str:
        sha = self._mirror.resolve(repository_id, revision)
        if not sha:
            raise NotFound(f"revision not found: {revision}")
        return sha

    def _diff_entities(
        self, base_path: str, head_path: str, result: ComparisonResult
    ) -> None:
        base = _entity_index(base_path)
        head = _entity_index(head_path)
        result.entities_added = [head[i]["entity"] for i in head if i not in base]
        result.entities_removed = [base[i]["entity"] for i in base if i not in head]
        result.entities_changed = [
            head[i]["entity"]
            for i in head
            if i in base and head[i]["signature"] != base[i]["signature"]
        ]

    def _collect_commits(
        self, repository_id: str, base_sha: str, head_sha: str, result: ComparisonResult
    ) -> None:
        shas = self._mirror.commits_between(repository_id, base_sha, head_sha)
        authors: list[str] = []
        with self._db.connect() as conn:
            for sha in shas:
                commit = self._commits.find_one(conn, repository_id, sha)
                if not commit:
                    continue
                result.commits.append({
                    "sha": sha, "subject": commit["subject"],
                    "author_name": commit["author_name"], "author_email": commit["author_email"],
                })
                if commit["author_email"] not in authors:
                    authors.append(commit["author_email"])
        result.authors = authors


def _entity_index(artifact_path: str) -> dict[str, dict]:
    database = EngineDatabase(Path(artifact_path))
    try:
        index = {}
        for entity in EngineRepository(database).iter_entities():
            index[entity.id] = {
                "signature": entity.signature or "",
                "entity": {"id": entity.id, "name": entity.name, "kind": entity.kind,
                           "file": entity.owner_file},
            }
        return index
    finally:
        database.close()
