from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..index.embedder import ChunkEmbedder
from ..repo.diff import FileDiff
from ..storage.dao import IndexStore
from .models import ReviewUnit
from .xref import CrossReferences, render as render_xrefs

CHARS_PER_TOKEN = 4
RAG_RESULTS = 10
MAX_NEIGHBOURS = 24
BODY_LIMIT_CHARS = 1800
MAX_CALLED = 16
# A name the added lines call. New code is not in the index, so it has no edges
# and the call graph cannot reach what it uses.
CALL_SITE = re.compile(r"(?:self\.)?([A-Za-z_]\w{3,})\s*\(")
# A name the change defines is already on the page. Looking it up in the index
# returns the version from before the change, or nothing.
DEFINED = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")
SELF_CALL = re.compile(r"self\.([A-Za-z_]\w{3,})\s*\(")
NOT_A_CALL = {"print", "super", "range", "len", "str", "int", "list", "dict", "set",
              "tuple", "bool", "float", "isinstance", "getattr", "setattr", "hasattr",
              "return", "assert", "raise", "yield", "await", "if", "for", "while",
              "with", "except", "self", "format", "join", "append", "get", "type"}


@dataclass
class UnitContext:
    diff_text: str = ""
    neighbours: str = ""
    cross_language: str = ""
    similar: str = ""
    siblings: str = ""
    truncated: list[str] = field(default_factory=list)
    rag_available: bool = True
    tokens: int = 0

    def render(self) -> str:
        parts = [f"CHANGED CODE UNDER REVIEW\n\n{self.diff_text}"]
        if self.siblings:
            parts.append(f"THE REST OF THIS PULL REQUEST\n\n{self.siblings}")
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

        context.siblings, sibling_tokens = self.siblings(unit_diffs, diffs, budget_tokens - used)
        used += sibling_tokens

        context.cross_language = self.cross_language(unit_diffs, head_sha)
        used += estimate(context.cross_language)

        remaining = budget_tokens - used
        neighbours, neighbour_tokens, skipped = self.call_graph_context(
            unit_diffs, diffs, remaining
        )
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

    def siblings(
        self, unit_diffs: list[FileDiff], diffs: list[FileDiff], budget_tokens: int
    ) -> tuple[str, int]:
        """The rest of the change: every other file by name, and in full when
        this unit names it.

        A unit that inherits from a class another unit adds must not guess at
        it. The planner splits the files; the pull request is still one change.
        """
        own = {item.path for item in unit_diffs}
        others = [item for item in diffs if item.path not in own]
        if not others:
            return "", 0

        lines = [
            f"- {item.path} ({item.status}, +{item.added_count}/-{item.removed_count})"
            for item in others
        ]
        text = "\n".join(lines)
        used = estimate(text)

        mine = "\n".join(item.render() for item in unit_diffs)
        for other in others:
            if not names(mine, other.path):
                continue
            rendered = other.render()
            cost = estimate(rendered)
            if used + cost > budget_tokens:
                break
            text += f"\n\n{rendered}"
            used += cost
        return text, used

    def cross_language(self, diffs: list[FileDiff], head_sha: str | None) -> str:
        if self.xrefs is None:
            return ""
        return render_xrefs(self.xrefs.find(diffs, head_sha))

    def call_graph_context(
        self, unit_diffs: list[FileDiff], diffs: list[FileDiff], budget_tokens: int
    ) -> tuple[str, int, list[str]]:
        if budget_tokens <= 0:
            return "", 0, ["call-graph neighbours"]

        # what the new code calls comes first: the slice below is what fits, and a
        # name this change actually calls beats an arbitrary neighbour
        related = self.called_by_new_code(unit_diffs, diffs) + self.collect_related(unit_diffs)
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

    def called_by_new_code(
        self, unit_diffs: list[FileDiff], diffs: list[FileDiff]
    ) -> list[dict]:
        """What the added lines call, looked up by name.

        A method added in this change is not in the index, so it has no edges
        and the call graph cannot reach what it uses. Its body still names that
        code, and that code is indexed.

        The whole change is read, not only this unit. A unit often reviews a
        caller while the method it calls was added in another unit, and the
        answer to "does this persist" lives one hop below that method.
        """
        own = self.called_names(unit_diffs)
        entries = []
        for name in self.ranked_calls(unit_diffs, diffs, own):
            for symbol in self.store.symbols_named(name, limit=1):
                entries.append(self.entry(symbol, f"called by the new code ({name})"))
            if len(entries) >= MAX_CALLED:
                break
        return entries

    def ranked_calls(
        self, unit_diffs: list[FileDiff], diffs: list[FileDiff], own: set[str]
    ) -> list[str]:
        """What is worth a slot, best first.

        Alphabetical order spent every slot on `Bench` and `from_dict` and cut
        off `_transition`, which was the one name that answered the question.
        A private method reached through `self` is the behaviour of the change;
        a bare constructor is a type the reviewer can already guess.
        """
        inner = {
            found
            for file_diff in diffs
            for _, text in file_diff.added_lines
            for found in SELF_CALL.findall(text)
        }
        names = self.called_names(diffs)
        return sorted(
            names,
            key=lambda name: (
                not name.startswith("_"),
                name not in inner,
                name not in own,
                name,
            ),
        )

    def called_names(self, diffs: list[FileDiff]) -> set[str]:
        names: set[str] = set()
        for file_diff in diffs:
            for _, text in file_diff.added_lines:
                names.update(CALL_SITE.findall(text))
        return names - NOT_A_CALL - self.defined_names(diffs)

    def defined_names(self, diffs: list[FileDiff]) -> set[str]:
        return {
            found.group(1)
            for file_diff in diffs
            for _, text in file_diff.added_lines
            if (found := DEFINED.match(text))
        }

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
        body = self.store.symbol_body(symbol["id"])
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


def names(text: str, path: str) -> bool:
    """Does this diff mention that file, as an import or by its name?"""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    module = path.rsplit(".", 1)[0].replace("/", ".")
    return stem in text or module in text


def estimate(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN
