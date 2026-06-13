"""Temporal application service (design/13).

Composes the deterministic git-change model, the temporal repository, and the
git-notes attachment into the operations the CLI and MCP expose: analyze a
change, record it against an episode, author decisions/alternatives, and
retrieve why an entity or commit range changed. Deterministic facts are kept
distinct from generated summaries; nothing here invents rationale or marks a
generated summary confirmed.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from beagle.database.repository import Repository
from beagle.temporal.changes import ChangeAnalyzer, changeset, parse_diff
from beagle.temporal.git import Git, GitError
from beagle.temporal.models import (
    Alternative, ChangeEpisode, ChangeReport, CommitRecord, Decision,
    EntityChange, FollowUp,
)
from beagle.temporal.notes import GitNotes
from beagle.temporal.redact import redact
from beagle.temporal.repository import TemporalRepository

_PENALIZED = {"superseded", "abandoned", "rejected"}


class TemporalService:
    def __init__(self, root: Path, repo: Repository, temporal: TemporalRepository):
        self.root = Path(root)
        self.repo = repo
        self.store = temporal
        self.git = Git(self.root)
        self.notes = GitNotes(self.git)

    # --- analysis (Phase A) ------------------------------------------------

    def analyze(self, spec: Optional[str] = None) -> ChangeReport:
        if not self.git.is_repo():
            return ChangeReport(None, None, notes=["not a git repository"])
        base, head, working = self._resolve_spec(spec)
        analyzer = ChangeAnalyzer(self.repo, indexed_head=working or head == self.git.head())
        diff = self._diff_for(base, head, working)
        changes = analyzer.entity_changes(parse_diff(diff))
        commits = [] if working else self._commit_records(base, head)
        for change in changes:
            change.commit_sha = head if not working else None
        patch_id = self.git.patch_id(diff)
        cs = changeset(base, head, patch_id, changes)
        report = ChangeReport(base, head, commits, changes, cs)
        if working and not changes:
            report.notes.append("working tree clean")
        if not analyzer.indexed_head:
            report.notes.append("head differs from indexed tree; mapping is path-level")
        return report

    def _resolve_spec(self, spec: Optional[str]):
        if not spec:
            return self.git.head(), None, True               # working tree vs HEAD
        if ".." in spec:
            base, _, head = spec.partition("..")
            return self.git.rev_parse(base), self.git.rev_parse(head) or head, False
        sha = self.git.rev_parse(spec) or spec
        parents = self.git.commit_meta(sha)["parents"]
        return (parents[0] if parents else None), sha, False

    def _diff_for(self, base, head, working: bool) -> str:
        if working:
            return self.git.diff_working()
        if base is None and head:
            return self.git.diff_commit(head)
        return self.git.diff_range(base, head)

    def _commit_records(self, base: Optional[str], head: Optional[str]) -> list[CommitRecord]:
        if not head:
            return []
        records = []
        for sha in self.git.commits_in_range(base, head):
            meta = self.git.commit_meta(sha)
            records.append(CommitRecord(
                sha, meta["parents"], meta["message"], meta["author"],
                meta["timestamp"], self.git.patch_id(self.git.diff_commit(sha))))
        return records

    # --- recording (Phase B/E) ---------------------------------------------

    def record(self, report: ChangeReport, episode_id: Optional[str] = None,
               write_note: bool = False) -> dict:
        for commit in report.commits:
            commit.episode_id = episode_id
            self.store.save_commit(commit)
        for change in report.entity_changes:
            change.episode_id = episode_id
            self.store.save_entity_change(change)
        if report.changeset:
            report.changeset.episode_id = episode_id
            self.store.save_changeset(report.changeset)
        if episode_id:
            self._touch_episode(episode_id, report)
        if write_note and episode_id and report.head_commit and report.changeset:
            self.notes.attach_episode(report.head_commit, episode_id, report.changeset)
        return {"commits": len(report.commits), "entity_changes": len(report.entity_changes)}

    def _touch_episode(self, episode_id: str, report: ChangeReport) -> None:
        ep = self.store.get_episode(episode_id)
        if ep is None:
            return
        ep.base_commit = ep.base_commit or report.base_commit
        ep.head_commit = report.head_commit or ep.head_commit
        ep.updated_at = time.time()
        self.store.save_episode(ep)

    # --- episode authoring (Phase D, manual) -------------------------------

    def new_episode(self, title: str, problem: Optional[str] = None,
                    goal: Optional[str] = None, status: str = "draft") -> ChangeEpisode:
        now = time.time()
        ep = ChangeEpisode(
            id=self._episode_id(title), title=title, status=status,
            created_at=now, updated_at=now, branch=self.git.branch(),
            problem=redact(problem) if problem else None,
            goal=redact(goal) if goal else None, confirmation="edited")
        self.store.save_episode(ep)
        return ep

    def _episode_id(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "episode"
        base, candidate, n = f"episode-{slug}", f"episode-{slug}", 1
        while self.store.get_episode(candidate) is not None:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def add_decision(self, episode_id: str, statement: str, rationale: Optional[str] = None,
                     status: str = "accepted", confirmation: str = "edited") -> Decision:
        d = Decision(
            id=self._child_id(episode_id, "d"), episode_id=episode_id,
            statement=redact(statement), rationale=redact(rationale) if rationale else None,
            status=status, created_at=time.time(), confirmation=confirmation)
        self.store.save_decision(d)
        return d

    def supersede_decision(self, old_id: str, episode_id: str, statement: str,
                           rationale: Optional[str] = None) -> Decision:
        new = self.add_decision(episode_id, statement, rationale, status="accepted")
        for d in self.store.decisions_for(episode_id):
            if d.id == old_id:
                d.status, d.superseded_by = "superseded", new.id
                self.store.save_decision(d)
        return new

    def add_alternative(self, episode_id: str, description: str,
                        rejection_reason: Optional[str] = None) -> Alternative:
        a = Alternative(
            id=self._child_id(episode_id, "a"), episode_id=episode_id,
            description=redact(description), status="rejected",
            rejection_reason=redact(rejection_reason) if rejection_reason else None)
        self.store.save_alternative(a)
        return a

    def add_followup(self, episode_id: str, description: str,
                     priority: str = "normal") -> FollowUp:
        f = FollowUp(id=self._child_id(episode_id, "f"), episode_id=episode_id,
                     description=redact(description), priority=priority)
        self.store.save_followup(f)
        return f

    def _child_id(self, episode_id: str, prefix: str) -> str:
        counts = {"d": self.store.decisions_for, "a": self.store.alternatives_for,
                  "f": self.store.followups_for}
        return f"{episode_id}-{prefix}{len(counts[prefix](episode_id)) + 1}"

    def finalize_episode(self, episode_id: str, status: str = "implemented",
                         outcome: Optional[str] = None) -> Optional[ChangeEpisode]:
        ep = self.store.get_episode(episode_id)
        if ep is None:
            return None
        ep.status = status
        ep.outcome = redact(outcome) if outcome else ep.outcome
        ep.updated_at = time.time()
        self.store.save_episode(ep)
        return ep

    def attach_commit(self, sha: str, episode_id: str, write_note: bool = True) -> dict:
        report = self.analyze(sha)
        return self.record(report, episode_id=episode_id, write_note=write_note)

    # --- retrieval (Phase G) -----------------------------------------------

    def episode_bundle(self, episode_id: str) -> Optional[dict]:
        ep = self.store.get_episode(episode_id)
        if ep is None:
            return None
        return {
            "episode": ep,
            "decisions": self.store.decisions_for(episode_id),
            "alternatives": self.store.alternatives_for(episode_id),
            "commits": self.store.commits_for(episode_id),
            "changes": self.store.changes_for_episode(episode_id),
            "followups": self.store.followups_for(episode_id),
        }

    def entity_history(self, ref: str) -> dict:
        entity_id = self._resolve_entity(ref)
        if entity_id is None:
            return {"error": f"no entity matches: {ref}"}
        episode_ids = self.store.episodes_for_entity(entity_id)
        episodes = [self.store.get_episode(e) for e in episode_ids]
        decisions = [d for e in episode_ids for d in self.store.decisions_for(e)]
        return {
            "entity_id": entity_id,
            "changes": self.store.changes_for_entity(entity_id),
            "episodes": _rank_episodes([e for e in episodes if e]),
            "decisions": _rank_decisions(decisions),
        }

    def _resolve_entity(self, ref: str) -> Optional[str]:
        if self.repo.get_entity(ref) is not None:
            return ref
        matches = self.repo.find_entities_by_name(ref)
        return matches[0].id if len(matches) == 1 else None

    def explain_range(self, spec: str) -> dict:
        report = self.analyze(spec)
        match = self.match_changeset(report)
        episode_ids = {c.episode_id for c in report.entity_changes if c.episode_id}
        if match and match.episode_id:
            episode_ids.add(match.episode_id)
        episodes = [self.store.get_episode(e) for e in episode_ids]
        return {"report": report, "linked_episodes": [e for e in episodes if e],
                "match": match}

    # --- rebase/squash recovery (Phase F, deterministic matchers) ----------

    def match_changeset(self, report: ChangeReport):
        cs = report.changeset
        if cs is None:
            return None
        if cs.patch_id:
            hit = self.store.find_changeset_by_patch(cs.patch_id)
            if hit:
                return hit
        if cs.entity_fingerprint:
            return self.store.find_changeset_by_fingerprint(cs.entity_fingerprint)
        return None


def _rank_episodes(episodes: list[ChangeEpisode]) -> list[ChangeEpisode]:
    return sorted(episodes, key=lambda e: (e.status in _PENALIZED, -e.updated_at))


def _rank_decisions(decisions: list[Decision]) -> list[Decision]:
    # Confirmed/accepted first; superseded shown but never hidden (design/13).
    def key(d: Decision):
        return (d.status in _PENALIZED, d.confirmation != "confirmed", -d.created_at)
    return sorted(decisions, key=key)
