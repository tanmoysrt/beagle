from __future__ import annotations

import logging
import re

from ..index.embedder import ChunkEmbedder
from ..repo.mirror import Mirror
from ..storage.dao import IndexStore

log = logging.getLogger("beagle.pipeline.tools")

FILE_LINE_LIMIT = 200
RESULT_LIMIT = 20000
GREP_CONTEXT = 2
GREP_LINE_LIMIT = 160

# `git grep -C` marks a match with a colon and a context line with a dash.
GREP_ROW = re.compile(r"^(?P<path>.+?)(?P<sep>[:-])(?P<line>\d+)[:-](?P<text>.*)$")
SYMBOL_MATCHES = 3
BODY_LIMIT_CHARS = 4000
SNIPPET_LINES = 6
CALL_LIMIT = 25
HISTORY_FORMAT = "%h %ad %an: %s"

TOOL_SPECS = [
    {
        "name": "read_file",
        "description": (
            "Read lines `start_line` to `end_line` of a file at the reviewed commit, with "
            "line numbers. Find the place with `grep` first, then read the lines around "
            f"it. Without a range the read stops at {FILE_LINE_LIMIT} lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository-relative path"},
                "start_line": {"type": "integer", "description": "First line to read, from 1"},
                "end_line": {"type": "integer", "description": "Last line to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_symbol",
        "description": (
            "Read the body of a function, class or method by name, from the index. "
            "Use it when you know the name but not the file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_name": {"type": "string"},
                "kind": {"type": "string", "description": "function, class, method"},
            },
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_callers",
        "description": (
            "List the places that call a symbol: path, line and signature only. "
            "Read the ones that matter with read_symbol or read_file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_callees",
        "description": "List what a symbol calls: path, line and signature only.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Find code with a related meaning, by example or by description. "
            "Use it for a pattern the call graph cannot reach."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search the whole repository for an exact string: a route, a config key, an "
            "error message, an import path, an environment variable. Each hit comes with "
            "its path, its line number and the lines around it. Start here, then use "
            "`read_file` on the range you want. This also finds the caller in another "
            "language that reaches the change by name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Literal text, not a regexp"},
                "path_glob": {"type": "string", "description": "e.g. *.py or src/**"},
                "context_lines": {
                    "type": "integer",
                    "description": f"Lines to show around each hit, {GREP_CONTEXT} by default",
                },
                "max_results": {"type": "integer"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "git_history",
        "description": (
            "Recent commits that touched a file, or that added or removed a name. "
            "Use it to learn why the code is as it is before you call it a defect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path_or_symbol": {"type": "string"},
                "max_entries": {"type": "integer"},
            },
            "required": ["path_or_symbol"],
        },
    },
]

TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


class Toolbox:
    """The repository as read-only calls the reviewer makes for itself.

    A tool returns what it found and never what it means; the judgment is the
    model's, so a result is evidence rather than an opinion.
    """

    def __init__(
        self,
        mirror: Mirror,
        store: IndexStore,
        head_sha: str | None,
        embedder: ChunkEmbedder | None = None,
        focus: list[str] | None = None,
    ):
        self.mirror = mirror
        self.store = store
        self.head_sha = head_sha
        self.embedder = embedder
        self.focus = set(focus or [])

    def run(self, name: str, arguments: dict) -> str:
        if name not in TOOL_NAMES:
            return f"there is no tool named {name}"
        try:
            result = getattr(self, name)(**arguments) or "nothing found"
        except TypeError as exc:
            return f"{name} rejected those arguments: {exc}"
        except Exception as exc:
            log.info("tool %s failed: %s", name, exc)
            return f"{name} failed: {exc}"
        if len(result) <= RESULT_LIMIT:
            return result
        return result[:RESULT_LIMIT] + "\n(result cut short; ask for a narrower range.)"

    def read_file(self, path: str, start_line: int = 0, end_line: int = 0) -> str:
        lines = self.text_of(path).splitlines()
        if not lines:
            return f"{path} is empty"
        start = max(1, start_line or 1)
        end = min(len(lines), end_line or len(lines))
        note = ""
        if not end_line and end - start + 1 > FILE_LINE_LIMIT:
            end = start + FILE_LINE_LIMIT - 1
            note = (
                f"\n\n({path} has {len(lines)} lines; stopped at {end}. "
                "Ask for a line range to see the rest.)"
            )
        body = "\n".join(f"{number:>6}  {lines[number - 1]}" for number in range(start, end + 1))
        return f"{path}:{start}-{end}\n{body}{note}"

    def read_symbol(self, symbol_name: str, kind: str = "") -> str:
        rows = self.store.symbols_named(symbol_name)
        if kind:
            rows = [row for row in rows if row.get("kind") == kind] or rows
        if not rows:
            return f"the index holds no symbol named {symbol_name}"
        blocks = []
        for row in self.ranked(rows)[:SYMBOL_MATCHES]:
            body = self.store.symbol_body(row["id"]) or self.slice_of(row)
            blocks.append(
                f"{row['path']}:{row['start_line']}-{row['end_line']} "
                f"{row['kind']} {row.get('qualified_name') or row['name']}\n"
                f"{(body or '')[:BODY_LIMIT_CHARS]}"
            )
        more = len(rows) - len(blocks)
        tail = f"\n\n({more} further match(es) not shown.)" if more > 0 else ""
        return "\n\n".join(blocks) + tail

    def find_callers(self, symbol_name: str) -> str:
        lines = []
        for symbol in self.store.symbols_named(symbol_name):
            for caller in self.store.callers_of(symbol["id"]):
                lines.append(self.signature_line(caller))
        return self.listing(lines, f"nothing in the index calls {symbol_name}")

    def find_callees(self, symbol_name: str) -> str:
        lines = []
        for symbol in self.store.symbols_named(symbol_name):
            for callee in self.store.callees_of(symbol["id"]):
                if callee.get("path"):
                    lines.append(self.signature_line(callee))
                elif callee.get("dst_name"):
                    lines.append(f"(outside the index) {callee['dst_name']}")
        return self.listing(lines, f"{symbol_name} calls nothing the index resolved")

    def search_code(self, query: str, max_results: int = 10) -> str:
        if self.embedder is None:
            return "semantic search is not available for this repository"
        hits = self.embedder.search(query, k=max(1, min(max_results, 20)))
        blocks = []
        for hit in hits:
            head = "\n".join((hit["body"] or "").splitlines()[:SNIPPET_LINES])
            blocks.append(
                f"{hit['path']}:{hit['start_line']}-{hit['end_line']} "
                f"(similarity {hit['similarity']})\n{head}"
            )
        return "\n\n".join(blocks) or "nothing similar in the index"

    def grep(
        self,
        pattern: str,
        path_glob: str = "",
        context_lines: int = GREP_CONTEXT,
        max_results: int = 20,
    ) -> str:
        if not self.head_sha:
            return "the reviewed commit is not available, so the tree cannot be searched"
        around = max(0, min(context_lines, 10))
        args = ["grep", "-n", "--fixed-strings", "-I", f"-C{around}", "-e", pattern, self.head_sha]
        if path_glob:
            args += ["--", path_glob]
        try:
            raw = self.mirror.run(args)
        except Exception:
            return f"no file contains {pattern}"
        wanted = max(1, min(max_results, 50))
        lines, hits = [], 0
        for row in raw.splitlines():
            found = GREP_ROW.match(row.removeprefix(f"{self.head_sha}:"))
            if found is None:
                lines.append("--")
                continue
            lines.append(f"{found['path']}:{found['line']}: {found['text'][:200]}")
            hits += found["sep"] == ":"
            if hits >= wanted or len(lines) >= GREP_LINE_LIMIT:
                break
        if hits >= wanted:
            lines.append(f"(stopped at {wanted} matches.)")
        return "\n".join(lines) or f"no file contains {pattern}"

    def git_history(self, path_or_symbol: str, max_entries: int = 10) -> str:
        if not self.head_sha:
            return "the reviewed commit is not available, so the history cannot be read"
        count = max(1, min(max_entries, 20))
        lines = []
        if looks_like_path(path_or_symbol):
            lines = self.log(["--follow", self.head_sha, "--", path_or_symbol], count)
        # a name that reads like a path is still only a guess
        return self.listing(
            lines or self.log(["-S", path_or_symbol, self.head_sha], count),
            f"no commit touched {path_or_symbol}",
        )

    def log(self, selector: list[str], count: int) -> list[str]:
        args = ["log", f"--format={HISTORY_FORMAT}", "--date=short", "--shortstat", "-n", str(count)]
        try:
            raw = self.mirror.run(args + selector)
        except Exception:
            return []
        return [row.strip() for row in raw.splitlines() if row.strip()]

    def ranked(self, rows: list[dict]) -> list[dict]:
        """A match inside the change under review answers the question first."""
        return sorted(rows, key=lambda row: row["path"] not in self.focus)

    def signature_line(self, symbol: dict) -> str:
        name = symbol.get("qualified_name") or symbol.get("name")
        return f"{symbol['path']}:{symbol['start_line']} {name} — {symbol.get('signature') or name}"

    def listing(self, lines: list[str], empty: str) -> str:
        unique = list(dict.fromkeys(lines))
        text = "\n".join(unique[:CALL_LIMIT])
        if len(unique) > CALL_LIMIT:
            text += f"\n({len(unique) - CALL_LIMIT} more not shown.)"
        return text or empty

    def slice_of(self, row: dict) -> str:
        """A symbol the embedder never chunked still has its lines in the tree."""
        lines = self.text_of(row["path"]).splitlines()
        return "\n".join(lines[row["start_line"] - 1 : row["end_line"]])

    def text_of(self, path: str) -> str:
        if not self.head_sha:
            raise RuntimeError("the reviewed commit is not available")
        return self.mirror.read_file(self.head_sha, path).decode("utf-8", errors="replace")


def looks_like_path(value: str) -> bool:
    return "/" in value or "." in value.strip(".")
