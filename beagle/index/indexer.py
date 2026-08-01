from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field

from ..repo.mirror import Mirror
from ..repo.selection import FileSelector, SelectedFile, looks_binary
from ..storage.dao import IndexStore
from .chunking import chunk_file
from .graph import GraphBuilder, symbol_key
from .symbols import ParsedFile, SymbolExtractor


@dataclass
class IndexReport:
    sha: str
    files_indexed: int = 0
    files_removed: int = 0
    files_unchanged: int = 0
    symbols: int = 0
    edges: int = 0
    edges_repaired: int = 0
    chunks: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0
    full: bool = False


class Indexer:
    """Keeps the structural index in step with a commit.

    There is one index per repository and it always reflects a known commit;
    pull request diffs are overlaid at review time and never written here.
    """

    def __init__(self, store: IndexStore, mirror: Mirror, selector: FileSelector):
        self.store = store
        self.mirror = mirror
        self.selector = selector
        self.extractor = SymbolExtractor()
        self.graph = GraphBuilder(store)
        self.lock = threading.Lock()

    @property
    def indexed_sha(self) -> str | None:
        return self.store.get_state("sha")

    def status(self) -> dict:
        state = {
            "sha": self.indexed_sha,
            "progress": self.store.get_state("progress", {}),
            "pending_embeddings": self.store.pending_chunk_count(),
        }
        state.update(self.store.counts())
        return state

    def sync(self, sha: str, full: bool = False) -> IndexReport:
        with self.lock:
            return self.run_sync(sha, full)

    def run_sync(self, sha: str, full: bool) -> IndexReport:
        started = time.monotonic()
        previous = self.indexed_sha
        do_full = full or previous is None or not self.mirror.has_commit(previous)
        report = IndexReport(sha=sha, full=do_full)

        selection = self.selector.select(sha)
        report.skipped = [(skip.path, skip.reason) for skip in selection.skipped]
        wanted = {file.path: file for file in selection.files}

        if do_full:
            targets = list(wanted.values())
            self.drop_removed(set(wanted))
        else:
            targets, removed = self.incremental_targets(previous, sha, wanted)
            report.files_removed = removed

        known_hashes = self.store.known_hashes()
        self.set_progress(sha, 0, len(targets))

        for position, selected in enumerate(targets, start=1):
            outcome = self.index_file(sha, selected, known_hashes)
            if outcome is None:
                report.files_unchanged += 1
            else:
                report.files_indexed += 1
                report.symbols += outcome[0]
                report.edges += outcome[1]
                report.chunks += outcome[2]
            if position % 25 == 0 or position == len(targets):
                self.set_progress(sha, position, len(targets))

        report.edges_repaired = self.graph.repair_unresolved()
        self.store.set_state("sha", sha)
        self.store.set_state("progress", {"done": len(targets), "total": len(targets), "sha": sha})
        report.seconds = round(time.monotonic() - started, 2)
        return report

    def incremental_targets(
        self, previous: str, sha: str, wanted: dict[str, SelectedFile]
    ) -> tuple[list[SelectedFile], int]:
        removed = 0
        targets: list[SelectedFile] = []
        for change in self.mirror.changed_files(previous, sha):
            if change.old_path:
                self.store.delete_file(change.old_path)
            if change.status == "D" or change.path not in wanted:
                self.store.delete_file(change.path)
                removed += 1
                continue
            targets.append(wanted[change.path])
        # anything selected but never indexed (new ignore rules, earlier failures)
        indexed = self.store.known_paths()
        targets.extend(file for path, file in wanted.items() if path not in indexed and file not in targets)
        return targets, removed

    def drop_removed(self, current_paths: set[str]) -> None:
        for path in self.store.known_paths() - current_paths:
            self.store.delete_file(path)

    def index_file(
        self, sha: str, selected: SelectedFile, known_hashes: dict[str, str]
    ) -> tuple[int, int, int] | None:
        content = self.mirror.read_blob(selected.blob_sha)
        if looks_binary(content):
            return None
        content_hash = hashlib.sha256(content).hexdigest()
        if known_hashes.get(selected.path) == content_hash:
            return None

        source = content.decode("utf-8", errors="replace")
        parsed = self.parse(selected, content)
        file_id = self.store.replace_file(
            selected.path, selected.lang, selected.blob_sha, content_hash, selected.size
        )
        symbol_ids = self.store_symbols(file_id, parsed)
        edges = self.graph.edges_for(parsed, symbol_ids) if parsed.symbols else []
        self.store.insert_edges(
            [(e.src_symbol_id, e.dst_symbol_id, e.dst_name, e.kind, e.resolution, e.line) for e in edges]
        )
        self.store.insert_imports(
            file_id, [(imp.module, imp.symbol, imp.alias, imp.line) for imp in parsed.imports]
        )
        chunks = chunk_file(selected.path, source, parsed.symbols)
        self.store.insert_chunks(
            [
                (
                    file_id,
                    symbol_ids.get(chunk.symbol_key) if chunk.symbol_key else None,
                    chunk.path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.content_hash,
                    chunk.token_estimate,
                    chunk.body,
                )
                for chunk in chunks
            ]
        )
        return len(parsed.symbols), len(edges), len(chunks)

    def parse(self, selected: SelectedFile, content: bytes) -> ParsedFile:
        if selected.lang is None:
            return ParsedFile(path=selected.path, lang="text")
        return self.extractor.parse(selected.path, selected.lang, content)

    def store_symbols(self, file_id: int, parsed: ParsedFile) -> dict[str, int]:
        rows = []
        for symbol in parsed.symbols:
            rows.append(
                {
                    "key": symbol_key(parsed.path, symbol),
                    "parent_key": symbol_key(parsed.path, symbol.parent) if symbol.parent else None,
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "kind": symbol.kind,
                    "lang": symbol.lang,
                    "signature": symbol.signature,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "start_byte": symbol.start_byte,
                    "end_byte": symbol.end_byte,
                }
            )
        return self.store.insert_symbols(file_id, rows)

    def set_progress(self, sha: str, done: int, total: int) -> None:
        self.store.set_state("progress", {"done": done, "total": total, "sha": sha})
