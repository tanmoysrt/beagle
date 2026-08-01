from __future__ import annotations

import time
from dataclasses import dataclass

from ..errors import ProviderError
from ..storage.dao import IndexStore
from .embeddings import EmbeddingClient
from .vectors import Neighbour, VectorStore

CONTEXT_HEADER = "# {path} lines {start}-{end}\n"


@dataclass
class EmbedReport:
    embedded: int = 0
    batches: int = 0
    remaining: int = 0
    degraded: bool = False
    error: str | None = None
    seconds: float = 0.0


class ChunkEmbedder:
    """Embeds pending chunks in batches, marking each batch done as it lands.

    Work already paid for is never repaid: an interrupted run resumes from the
    chunks that are still unmarked.
    """

    def __init__(self, store: IndexStore, vectors: VectorStore, client: EmbeddingClient, batch_size: int):
        self.store = store
        self.vectors = vectors
        self.client = client
        self.batch_size = batch_size

    def run(self, limit: int | None = None) -> EmbedReport:
        started = time.monotonic()
        report = EmbedReport()
        budget = limit if limit is not None else float("inf")

        while budget > 0:
            take = int(min(self.batch_size, budget))
            pending = self.store.pending_chunks(take)
            if not pending:
                break
            try:
                self.embed_batch(pending)
            except ProviderError as exc:
                report.degraded = True
                report.error = str(exc)
                break
            report.embedded += len(pending)
            report.batches += 1
            budget -= len(pending)
            self.store.set_state(
                "embedding_progress",
                {"embedded": report.embedded, "remaining": self.store.pending_chunk_count()},
            )

        report.remaining = self.store.pending_chunk_count()
        report.seconds = round(time.monotonic() - started, 2)
        return report

    def embed_batch(self, chunks: list[dict]) -> None:
        vectors = self.client.embed([embedding_text(chunk) for chunk in chunks])
        self.vectors.upsert_chunks(
            [(chunk["id"], vector) for chunk, vector in zip(chunks, vectors)]
        )
        self.store.mark_embedded([chunk["id"] for chunk in chunks])

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Nearest chunks to a piece of code or a question about it."""
        vector = self.client.embed([query])[0]
        neighbours = self.vectors.search_chunks(vector, k)
        return self.hydrate(neighbours)

    def hydrate(self, neighbours: list[Neighbour]) -> list[dict]:
        by_id = {row["id"]: row for row in self.store.chunks_by_ids([n.key for n in neighbours])}
        results = []
        for neighbour in neighbours:
            row = by_id.get(neighbour.key)
            if row:
                results.append({**row, "similarity": round(neighbour.similarity, 4)})
        return results


def embedding_text(chunk: dict) -> str:
    """Give the model the path and line span; retrieval quality improves with it."""
    header = CONTEXT_HEADER.format(
        path=chunk["path"], start=chunk["start_line"], end=chunk["end_line"]
    )
    return header + chunk["body"]
