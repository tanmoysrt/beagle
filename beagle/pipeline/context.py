from __future__ import annotations

from dataclasses import dataclass, field

from ..index.embedder import ChunkEmbedder
from ..repo.diff import FileDiff
from ..storage.dao import IndexStore
from .models import ReviewUnit
from .xref import CrossReferences, render as render_xrefs

CHARS_PER_TOKEN = 4
RAG_RESULTS = 4
MAX_NEIGHBOURS = 12
BODY_LIMIT_CHARS = 1800


@dataclass
class UnitContext:
    diff_text: str = ""
    neighbours: str = ""
    cross_language: str = ""
    similar: str = ""
    truncated: list[str] = field(default_factory=list)
    rag_available: bool = True
    tokens: int = 0

    def render(self) -> str:
        parts = [f"CHANGED CODE UNDER REVIEW\n\n{self.diff_text}"]
        if self.neighbours:
            parts.append(f"RELATED SYMBOLS FROM THE CALL GRAPH\n\n{self.neighbours}")
        if self.cross_language:
            parts.append(
                "OTHER FILES THAT STILL NAME WHAT THIS DIFF REMOVES OR RENAMES\n\n"
                f"{self.cross_language}"
            )
        if self.similar:
            parts.append(f"SIMILAR CODE ELSEWHERE IN THE REPOSITORY\n\n{self.similar}")
        if self.truncated:
            parts.append("NOT SHOWN (token budget): " + ", ".join(self.truncated))
        return "\n\n".join(parts)


class ContextBuilder:
    """Fills a unit's token budget: diff, then call-graph neighbours, then
    retrieved code. What does not fit is named, not dropped silently."""

    def __init__(
        self,
        store: IndexStore,
        embedder: ChunkEmbedder | None = None,
        xrefs: CrossReferences | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.xrefs = xrefs

    def build(
        self,
        unit: ReviewUnit,
        diffs: list[FileDiff],
        budget_tokens: int,
        head_sha: str | None = None,
    ) -> UnitContext:
        context = UnitContext()
        unit_diffs = [item for item in diffs if item.path in unit.paths]

        context.diff_text = "\n\n".join(item.render() for item in unit_diffs)
        used = estimate(context.diff_text)

        context.cross_language = self.cross_language(unit_diffs, head_sha)
        used += estimate(context.cross_language)

        remaining = budget_tokens - used
        neighbours, neighbour_tokens, skipped = self.call_graph_context(unit_diffs, remaining)
        context.neighbours = neighbours
        context.truncated.extend(skipped)
        used += neighbour_tokens

        remaining = budget_tokens - used
        if remaining > 500:
            similar, similar_tokens, available = self.similar_context(context.diff_text, unit, remaining)
            context.similar = similar
            context.rag_available = available
            used += similar_tokens
        elif self.embedder is not None:
            context.truncated.append("retrieved similar code")

        context.tokens = used
        return context

    def cross_language(self, diffs: list[FileDiff], head_sha: str | None) -> str:
        if self.xrefs is None:
            return ""
        return render_xrefs(self.xrefs.find(diffs, head_sha))

    def call_graph_context(
        self, diffs: list[FileDiff], budget_tokens: int
    ) -> tuple[str, int, list[str]]:
        if budget_tokens <= 0:
            return "", 0, ["call-graph neighbours"]

        related = self.collect_related(diffs)
        signatures, bodies, skipped = [], [], []
        used = 0

        for entry in related[:MAX_NEIGHBOURS]:
            line = f"{entry['path']}:{entry['start_line']} {entry['relation']} — {entry['signature']}"
            cost = estimate(line)
            if used + cost > budget_tokens:
                skipped.append(entry["qualified_name"])
                continue
            signatures.append(line)
            used += cost

        for entry in related[:MAX_NEIGHBOURS]:
            body = entry.get("body")
            if not body:
                continue
            cost = estimate(body)
            if used + cost > budget_tokens:
                break
            bodies.append(f"# {entry['path']}:{entry['start_line']} ({entry['relation']})\n{body}")
            used += cost

        text = "\n".join(signatures)
        if bodies:
            text += "\n\n" + "\n\n".join(bodies)
        return text, used, skipped

    def collect_related(self, diffs: list[FileDiff]) -> list[dict]:
        seen, related = set(), []
        for file_diff in diffs:
            for start, end in file_diff.changed_line_ranges:
                for symbol in self.store.symbols_overlapping(file_diff.path, start, end):
                    for entry in self.neighbours_of(symbol, file_diff.path):
                        key = (entry["path"], entry["qualified_name"])
                        if key in seen:
                            continue
                        seen.add(key)
                        related.append(entry)
        return related

    def neighbours_of(self, symbol: dict, own_path: str) -> list[dict]:
        entries = []
        for caller in self.store.callers_of(symbol["id"]):
            if caller["path"] != own_path:
                entries.append(self.entry(caller, f"calls {symbol['name']}"))
        for callee in self.store.callees_of(symbol["id"]):
            if callee.get("id") and callee.get("path") != own_path:
                entries.append(self.entry(callee, f"called by {symbol['name']}"))
        return entries

    def entry(self, symbol: dict, relation: str) -> dict:
        return {
            "path": symbol["path"],
            "qualified_name": symbol.get("qualified_name") or symbol.get("name"),
            "signature": symbol.get("signature") or symbol.get("name"),
            "start_line": symbol.get("start_line"),
            "relation": relation,
            "body": self.body_of(symbol),
        }

    def body_of(self, symbol: dict) -> str | None:
        rows = self.store.core.query(
            "select body from chunks where symbol_id = ? limit 1", (symbol["id"],)
        )
        if not rows:
            return None
        body = rows[0][0]
        return body[:BODY_LIMIT_CHARS] if body else None

    def similar_context(
        self, diff_text: str, unit: ReviewUnit, budget_tokens: int
    ) -> tuple[str, int, bool]:
        if self.embedder is None or not diff_text.strip():
            return "", 0, False
        try:
            hits = self.embedder.search(diff_text[:6000], k=RAG_RESULTS + len(unit.paths))
        except Exception:
            return "", 0, False

        blocks, used = [], 0
        for hit in hits:
            if hit["path"] in unit.paths:
                continue
            block = f"# {hit['path']}:{hit['start_line']}-{hit['end_line']}\n{hit['body']}"
            cost = estimate(block)
            if used + cost > budget_tokens:
                break
            blocks.append(block)
            used += cost
            if len(blocks) >= RAG_RESULTS:
                break
        return "\n\n".join(blocks), used, True


def estimate(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN
