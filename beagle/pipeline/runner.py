from __future__ import annotations

import json
import time

from ..config import Config, Severity
from ..errors import BudgetExceeded, ProviderError
from ..index.embedder import ChunkEmbedder
from ..llm.client import LLMClient, make_budget
from ..prompts.loader import PromptSet
from ..repo.diff import FileDiff, parse_diff
from ..repo.mirror import Mirror
from ..repo.selection import FileSelector
from ..scan.secrets import SecretScanner
from ..storage.dao import CallLog, IndexStore
from ..storage.migrations import utc_now
from .context import ContextBuilder
from .dedup import Merger
from .events import EventStream
from .instructions import InstructionFinder
from ..memory.filter import MemoryFilter
from .models import (
    Finding,
    ReviewUnit,
    ReviewRequest,
    ReviewResult,
    ReviewState,
    ReviewSummary,
    count_by_severity,
    score_for,
    verdict_for,
)
from .planner import Planner
from .review import UnitReviewer
from .risk import RiskTagger
from .security import SecurityClassifier
from .summary import Summariser
from .verify import Verifier
from .xref import CrossReferences


class ReviewRunner:
    """Runs the whole review and owns the policies that prompts must not weaken.

    The security floor, the finding caps and the severity floor are applied
    here in code, so an overridden prompt cannot quietly turn them off.
    """

    def __init__(
        self,
        config: Config,
        storage_core,
        mirror: Mirror,
        store: IndexStore,
        prompts: PromptSet,
        client: LLMClient,
        embedder: ChunkEmbedder | None = None,
        call_log: CallLog | None = None,
        memory: MemoryFilter | None = None,
    ):
        self.config = config
        self.core = storage_core
        self.mirror = mirror
        self.store = store
        self.prompts = prompts
        self.client = client
        self.embedder = embedder
        self.call_log = call_log

        self.selector = FileSelector(mirror, config.repo.ignore)
        self.instructions = InstructionFinder(mirror, config.context.instruction_files_extra)
        self.context_builder = ContextBuilder(store, embedder, CrossReferences(mirror))
        self.planner = Planner(client, prompts)
        self.risk = RiskTagger(store)
        self.reviewer = UnitReviewer(client, prompts, config.review)
        self.merger = Merger(client, prompts, config.review)
        self.security = SecurityClassifier()
        self.memory = memory or MemoryFilter(config.memory)
        self.verifier = Verifier(client, prompts)
        self.summariser = Summariser(client, prompts, config.review)
        self.scanner = SecretScanner()

    def run(self, request: ReviewRequest, events: EventStream) -> ReviewResult:
        state = ReviewState(request, events, make_budget(self.config.review))
        state.budget.reuse = not request.fresh
        try:
            return self.execute(state)
        except BudgetExceeded as exc:
            events.emit("error", message=str(exc), partial=True)
            return self.empty_result(state, str(exc))
        except ProviderError as exc:
            events.emit("error", message=str(exc))
            return self.empty_result(state, str(exc))

    def execute(self, state: ReviewState) -> ReviewResult:
        state.base_sha, state.head_sha, state.diffs, state.skipped = self.resolve_diff(
            state.request
        )
        state.events.emit(
            "review_started",
            review_id=state.review_id,
            base=state.base_sha,
            head=state.head_sha,
            files=len(state.diffs),
        )
        if not state.diffs:
            return self.empty_result(state, "no reviewable changes")

        # Scan hits are announced by count only; the final list emits them once.
        secrets = self.scanner.scan(state.diffs)
        if secrets:
            state.events.emit("unit_complete", unit="secret-scan", findings=len(secrets))
        state.findings.extend(secrets)

        state.units = self.risk.apply(
            self.planner.plan(state.diffs, state.review_id, state.budget)
        )
        prefix, state.instruction_files = self.build_prefix(state.head_sha, state.diffs)
        self.review_units(state, prefix)
        return self.finalize(state)

    def review_units(self, state: ReviewState, prefix: list[dict]) -> None:
        per_unit = self.per_unit_budget(state.units)
        for unit in state.units:
            state.events.emit("unit_started", unit=unit.key, title=unit.title, files=unit.paths)
            context = self.context_builder.build(unit, state.diffs, per_unit, state.head_sha)
            state.contexts[unit.key] = context.render()
            if self.embedder is not None and not context.rag_available:
                state.degraded.append("retrieval unavailable")
            reused_before = state.budget.reused
            try:
                findings, anomalies = self.reviewer.review(
                    unit, context, prefix, state.review_id, state.budget
                )
            except BudgetExceeded:
                state.degraded.append(
                    f"stopped after {state.covered} of {len(state.units)} units (budget)"
                )
                return
            state.degraded.extend(anomalies)
            state.covered += 1
            state.findings.extend(findings)
            state.events.emit(
                "unit_complete", unit=unit.key, findings=len(findings),
                reused=state.budget.reused > reused_before,
            )

    def finalize(self, state: ReviewState) -> ReviewResult:
        events, review_id = state.events, state.review_id
        merged, overflow = self.merger.merge(state.findings, review_id, state.budget)
        merged = self.security.apply(merged)

        outcome = self.memory.filter(merged)
        for finding in outcome.suppressed:
            events.emit("finding_suppressed", **finding.to_dict(review_id))

        kept, rejected = self.verifier.verify_all(
            outcome.kept, state.contexts, review_id, state.budget
        )
        kept = self.enforce_policy(kept)

        for finding in kept:
            events.emit("finding", **finding.to_dict(review_id))

        summary = self.summariser.build(
            kept, digest(state.diffs), state.coverage, review_id, state.budget
        )
        summary.verdict = verdict_for(kept, self.config.review.fail_on)
        summary.score = score_for(kept, state.coverage)
        summary.counts = count_by_severity(kept)
        summary.suppressed = len(outcome.suppressed)
        summary.overflow = overflow
        summary.instruction_files = state.instruction_files
        summary.skipped_files = state.skipped
        summary.degraded = sorted(set(state.degraded))
        self.attach_spend(summary, state)

        result = ReviewResult(
            review_id, summary, kept, rejected, outcome.suppressed, state.base_sha, state.head_sha
        )
        self.persist(result)
        self.memory.remember(kept + outcome.suppressed, review_id)
        events.emit("review_complete", **result.summary.to_dict(), findings=len(kept))
        return result

    def enforce_policy(self, findings: list[Finding]) -> list[Finding]:
        """Security findings ignore the floor; everything else respects it."""
        floor = self.config.review.min_severity
        return [
            demote_advice(finding)
            for finding in findings
            if finding.is_security or finding.severity.at_least(floor)
        ]

    def resolve_diff(
        self, request: ReviewRequest
    ) -> tuple[str | None, str | None, list[FileDiff], list[dict]]:
        if request.diff:
            diffs = [item for item in parse_diff(request.diff) if not item.binary and item.hunks]
            # A posted diff has no ref of its own, so fall back to the indexed commit
            # for repository context such as the instruction files.
            return None, self.store.get_state("sha"), diffs, []

        self.mirror.ensure()
        base = request.base or self.config.repo.default_base
        head = request.head or self.config.repo.default_base
        base_sha = self.mirror.resolve(base)
        head_sha = self.mirror.resolve(head)
        diffs = parse_diff(self.mirror.diff(base_sha, head_sha))
        selection = self.selector.select_paths(head_sha, [item.path for item in diffs])
        allowed = selection.paths
        skipped = [{"path": item.path, "reason": item.reason} for item in selection.skipped]
        return base_sha, head_sha, [item for item in diffs if item.path in allowed], skipped

    def build_prefix(self, head_sha: str | None, diffs: list[FileDiff]) -> tuple[list[dict], list[str]]:
        block, applied = "", []
        if head_sha and self.config.context.instruction_files == "auto":
            tracked = [entry.path for entry in self.mirror.list_tree(head_sha)]
            files = self.instructions.discover(head_sha, tracked)
            block, applied = self.instructions.block(
                files, [item.path for item in diffs], self.config.context.instruction_files_budget
            )
        prefix = self.reviewer.cached_prefix(
            repo_overview=self.repo_overview(),
            instruction_block=block,
            conventions=self.memory.conventions_block(),
        )
        return prefix, applied

    def repo_overview(self) -> str:
        counts = self.store.counts()
        languages = self.core.query(
            "select lang, count(*) from files where lang is not null group by lang order by 2 desc"
        )
        listed = ", ".join(f"{row[0]} ({row[1]} files)" for row in languages) or "unknown"
        return (
            f"REPOSITORY OVERVIEW\n{self.config.repo.url}\n"
            f"Indexed: {counts['files']} files, {counts['symbols']} symbols, "
            f"{counts['symbol_edges']} call-graph edges.\nLanguages: {listed}."
        )

    def per_unit_budget(self, units: list[ReviewUnit]) -> int:
        return max(4000, self.config.review.token_budget // max(1, len(units)))

    def attach_spend(self, summary: ReviewSummary, state: ReviewState) -> None:
        spent = state.budget.spent
        summary.cost_usd = round(spent.cost_usd, 4)
        summary.tokens_in = spent.tokens_in
        summary.tokens_out = spent.tokens_out
        summary.tokens_cached = spent.tokens_cached
        summary.duration_seconds = round(time.monotonic() - state.started, 2)
        summary.reused = state.budget.reused

    def empty_result(self, state: ReviewState, note: str) -> ReviewResult:
        summary = ReviewSummary(verdict="comment", description=note, notes=[note])
        self.attach_spend(summary, state)
        result = ReviewResult(
            state.review_id, summary, base_sha=state.base_sha, head_sha=state.head_sha
        )
        self.persist(result)
        return result

    def persist(self, result: ReviewResult) -> None:
        now = utc_now()
        summary = result.summary
        with self.core.tx() as conn:
            conn.execute("delete from findings where review_id = ?", (result.review_id,))
            conn.execute(
                "insert into reviews (id, base_sha, head_sha, status, verdict, confidence,"
                " coverage, description, summary_json, cost_usd, tokens_in, tokens_out,"
                " created_at, completed_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " on conflict(id) do update set base_sha=excluded.base_sha, head_sha=excluded.head_sha,"
                " status=excluded.status, verdict=excluded.verdict, confidence=excluded.confidence,"
                " coverage=excluded.coverage, description=excluded.description,"
                " summary_json=excluded.summary_json, cost_usd=excluded.cost_usd,"
                " tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out,"
                " completed_at=excluded.completed_at",
                (
                    result.review_id,
                    result.base_sha,
                    result.head_sha,
                    "complete",
                    summary.verdict,
                    summary.confidence,
                    summary.coverage,
                    summary.description,
                    json.dumps(summary.to_dict()),
                    summary.cost_usd,
                    summary.tokens_in,
                    summary.tokens_out,
                    now,
                    now,
                ),
            )
            for finding in result.stored():
                conn.execute(
                    "insert into findings (id, review_id, fingerprint, file, line_start, line_end,"
                    " category, severity, model_severity, confidence, app_code, title, body,"
                    " suggested_patch, context_used, metadata_json, status, created_at)"
                    " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    finding.as_row(result.review_id, now),
                )


def demote_advice(finding: Finding) -> Finding:
    """A missing test or a missing document is a nit, whatever severity the model chose."""
    if finding.category == "test_gap" and finding.severity.at_least(Severity.P4):
        finding.severity = Severity.P4
    return finding


def digest(diffs: list[FileDiff]) -> str:
    lines = ["DIFF SUMMARY:"]
    for item in diffs:
        lines.append(f"- {item.path} ({item.status}, +{item.added_count}/-{item.removed_count})")
    return "\n".join(lines)
