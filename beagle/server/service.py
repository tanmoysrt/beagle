from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from ..config import Config, ConfigProvider
from ..constants import LLM_LOG_RETENTION_DAYS, MIRROR_DIRNAME
from ..errors import BeagleError
from ..github.driver import GithubDriver
from ..index.embedder import ChunkEmbedder
from ..index.embeddings import EmbeddingClient
from ..index.indexer import Indexer
from ..index.vectors import VectorStore
from ..llm.client import LLMClient
from ..memory.calibration import Calibrator
from ..memory.filter import MemoryFilter
from ..memory.rules import RuleStore
from ..memory.suppression import SuppressionMemory
from ..pipeline.events import EventRegistry
from ..pipeline.runner import ReviewRequest, ReviewResult, ReviewRunner
from ..prompts.loader import PromptSet
from ..repo.mirror import Mirror
from ..repo.selection import FileSelector
from ..storage.dao import CallLog, IndexStore
from ..storage.db import Storage, open_storage
from ..storage.migrations import utc_now
from .queue import JobQueue
from .reporting import Reporter

log = logging.getLogger("beagle.service")
EMBEDDING_RETRY_SECONDS = 120


class BeagleService:
    """Everything the server owns, wired together once at startup."""

    def __init__(self, provider: ConfigProvider, data_dir: Path | str):
        self.provider = provider
        self.data_dir = Path(data_dir)
        config = provider.current

        self.storage: Storage = open_storage(self.data_dir, config.embeddings.dims)
        self.store = IndexStore(self.storage.core)
        self.call_log = CallLog(self.storage.llm_log)
        self.trim_call_log()

        self.mirror = Mirror(
            config.repo.url, self.data_dir / MIRROR_DIRNAME, token=config.github.token
        )
        self.selector = FileSelector(self.mirror, config.repo.ignore)
        self.vectors = VectorStore(self.storage.vectors, config.embeddings.dims)
        self.indexer = Indexer(self.store, self.mirror, self.selector, self.vectors)

        self.embeddings = EmbeddingClient(config.embeddings, self.call_log)
        self.embedder = ChunkEmbedder(
            self.store, self.vectors, self.embeddings, config.embeddings.batch_size
        )

        self.prompts = PromptSet(config.prompts.dir)
        self.llm = LLMClient(config.llm, self.call_log)

        self.rules = RuleStore(self.storage.core, self.llm, self.prompts)
        self.calibrator = Calibrator(self.storage.core)
        self.memory = MemoryFilter(
            config.memory,
            SuppressionMemory(self.storage.core, self.vectors, self.embeddings, config.memory),
            self.calibrator,
            self.rules,
        )

        self.events = EventRegistry()
        self.index_lock = threading.Lock()
        self.embeddings_blocked_until = 0.0
        self.embeddings_error: str | None = None

        self.queue = JobQueue(
            self.storage.core, config.server.max_parallel_reviews, self.handle_job
        )
        self.report = Reporter(self)
        self.github = GithubDriver(config.github, self) if config.github_enabled else None

    @property
    def config(self) -> Config:
        return self.provider.current

    def trim_call_log(self) -> None:
        trimmed = self.call_log.trim(LLM_LOG_RETENTION_DAYS)
        if trimmed:
            log.info("trimmed %d call log rows older than %d days", trimmed, LLM_LOG_RETENTION_DAYS)

    def runner(self) -> ReviewRunner:
        return ReviewRunner(
            config=self.config,
            storage_core=self.storage.core,
            mirror=self.mirror,
            store=self.store,
            prompts=self.prompts,
            client=self.llm,
            embedder=self.embedder,
            call_log=self.call_log,
            memory=self.memory,
        )

    def enqueue(self, kind: str, payload: dict[str, Any], review_id: str | None = None) -> int:
        return self.queue.enqueue(kind, payload, review_id)

    def handle_job(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "review":
            self.run(request_from(payload))
        elif kind == "index":
            self.run_index(payload.get("full", False))
        elif kind.startswith("github_"):
            if self.github is None:
                raise BeagleError("github integration is disabled")
            self.github.handle(kind, payload)
        else:
            raise BeagleError(f"unknown job kind: {kind}")

    def run(self, request: ReviewRequest) -> ReviewResult:
        """Index, then review. A failure reaches the stream before it propagates."""
        stream = self.events.reset(request.review_id)
        try:
            self.sync_index_for(request)
            return self.runner().run(request, stream)
        except Exception as exc:
            log.exception("review %s failed", request.review_id)
            stream.emit("error", message=str(exc))
            raise

    def record_feedback(
        self,
        finding_id: str,
        action: str,
        reason: str | None = None,
        author: str | None = None,
        weight: float = 1.0,
    ) -> dict | None:
        """The one place feedback is written, whether it came from the API or GitHub."""
        self.storage.core.execute(
            "insert into feedback (finding_id, fingerprint, action, reason, author, weight,"
            " created_at) select ?, fingerprint, ?, ?, ?, ?, ? from findings where id = ?",
            (finding_id, action, reason, author, weight, utc_now(), finding_id),
        )
        if action in ("false_positive", "dismiss", "style_rule"):
            self.storage.core.execute(
                "update findings set status = 'suppressed' where id = ?", (finding_id,)
            )
        if action == "style_rule" and reason:
            return self.rules.add(reason, author)
        return None

    def sync_index_for(self, request: ReviewRequest) -> None:
        """A review always runs against a known commit, never a per-review index."""
        if request.diff:
            return
        with self.index_lock:
            self.mirror.ensure()
            head = self.mirror.resolve(
                request.index_ref or request.head or self.config.repo.default_base
            )
            if self.indexer.indexed_sha != head:
                self.indexer.sync(head)
            self.embed_pending()

    def embed_pending(self, limit: int | None = None) -> dict[str, Any]:
        if time.monotonic() < self.embeddings_blocked_until:
            return {
                "embedded": 0,
                "remaining": self.store.pending_chunk_count(),
                "degraded": True,
                "error": self.embeddings_error,
            }
        report = self.embedder.run(limit=limit)
        if report.degraded:
            # Do not re-dial a dead endpoint on every review.
            self.embeddings_blocked_until = time.monotonic() + EMBEDDING_RETRY_SECONDS
            self.embeddings_error = report.error
            log.warning(
                "embeddings degraded, pausing for %ds: %s", EMBEDDING_RETRY_SECONDS, report.error
            )
        else:
            self.embeddings_blocked_until = 0.0
            self.embeddings_error = None
        return {
            "embedded": report.embedded,
            "remaining": report.remaining,
            "degraded": report.degraded,
            "error": report.error,
        }

    def run_index(self, full: bool = False) -> dict[str, Any]:
        with self.index_lock:
            self.mirror.ensure()
            head = self.mirror.resolve(self.config.repo.default_base)
            report = self.indexer.sync(head, full=full)
            embedded = self.embed_pending()
        return {
            "sha": report.sha,
            "files_indexed": report.files_indexed,
            "files_removed": report.files_removed,
            "symbols": report.symbols,
            "edges": report.edges,
            "chunks": report.chunks,
            "seconds": report.seconds,
            "skipped": [{"path": path, "reason": reason} for path, reason in report.skipped],
            "embeddings": embedded,
        }

    def close(self) -> None:
        self.embeddings.close()
        if self.github is not None:
            self.github.close()
        self.storage.close()


def request_from(payload: dict[str, Any]) -> ReviewRequest:
    return ReviewRequest(
        review_id=payload["review_id"],
        base=payload.get("base"),
        head=payload.get("head"),
        diff=payload.get("diff"),
        author=payload.get("author"),
        fresh=payload.get("fresh", False),
    )
