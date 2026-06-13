"""Score an index against the gold sets and the design/05 targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from beagle.benchmarks import gold
from beagle.context import ContextCompiler
from beagle.database.repository import Repository
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace


@dataclass
class Metric:
    name: str
    value: float
    target: float
    higher_is_better: bool = True

    @property
    def passed(self) -> bool:
        return self.value >= self.target if self.higher_is_better else self.value <= self.target


@dataclass
class Report:
    metrics: list[Metric] = field(default_factory=list)
    stale_facts: int = 0

    @property
    def passed(self) -> bool:
        return self.stale_facts == 0 and all(m.passed for m in self.metrics)


def _pr(produced: set, gold_set: set) -> tuple[float, float]:
    tp = len(produced & gold_set)
    precision = 100.0 * tp / len(produced) if produced else 100.0
    recall = 100.0 * tp / len(gold_set) if gold_set else 100.0
    return precision, recall


def score(workspace: Workspace) -> Report:
    repo = workspace.repo
    report = Report()
    report.metrics += _structural(repo)
    report.metrics += _retrieval(workspace)
    return report


# --- structural --------------------------------------------------------


def _structural(repo: Repository) -> list[Metric]:
    symbols = {e.id for e in repo.iter_entities() if e.kind in gold.SYMBOL_KINDS}
    sp, sr = _pr(symbols, gold.SYMBOLS)
    ip, ir = _pr(_resolved_pairs(repo, ("IMPORTS",)), gold.IMPORTS)
    cp, cr = _pr(_resolved_pairs(repo, ("CALLS",)), gold.CALLS)
    fp, fr = _pr(_resolved_triples(repo, gold.FRAPPE_RELATIONSHIPS), gold.FRAPPE)
    return [
        Metric("symbol_precision", sp, gold.TARGETS["symbol_precision"]),
        Metric("symbol_recall", sr, gold.TARGETS["symbol_recall"]),
        Metric("import_precision", ip, gold.TARGETS["import_precision"]),
        Metric("import_recall", ir, gold.TARGETS["import_recall"]),
        Metric("call_precision", cp, gold.TARGETS["call_precision"]),
        Metric("call_recall", cr, gold.TARGETS["call_recall"]),
        Metric("frappe_precision", fp, gold.TARGETS["frappe_precision"]),
        Metric("frappe_recall", fr, gold.TARGETS["frappe_recall"]),
    ]


def _resolved_pairs(repo: Repository, relationships: tuple[str, ...]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for rel in relationships:
        for row in repo.conn.execute(
            "SELECT source_id, target_id FROM edges WHERE relationship=? AND target_id IS NOT NULL",
            (rel,),
        ):
            out.add((row["source_id"], row["target_id"]))
    return out


def _resolved_triples(repo: Repository, relationships: tuple[str, ...]) -> set[tuple[str, str, str]]:
    placeholders = ",".join("?" * len(relationships))
    rows = repo.conn.execute(
        f"SELECT source_id, relationship, target_id FROM edges "
        f"WHERE relationship IN ({placeholders}) AND target_id IS NOT NULL",
        relationships,
    )
    return {(r["source_id"], r["relationship"], r["target_id"]) for r in rows}


# --- retrieval ---------------------------------------------------------


def _retrieval(workspace: Workspace) -> list[Metric]:
    graph = GraphService(workspace.repo)
    search = SearchEngine(workspace.db)
    compiler = ContextCompiler(workspace.repo, graph, search, workspace.read_range)
    return [
        Metric("exact_symbol", _exact_symbol(graph), gold.TARGETS["exact_symbol"]),
        Metric("top5", _top5(search), gold.TARGETS["top5"]),
        Metric("must_include", _must_include(compiler), gold.TARGETS["must_include"]),
        Metric("irrelevant", _irrelevant(compiler), gold.TARGETS["irrelevant_max"], higher_is_better=False),
    ]


def _exact_symbol(graph: GraphService) -> float:
    passes = sum(
        1 for query, expected in gold.EXACT_SYMBOL
        if expected in {e.id for e in graph.resolve(query)}
    )
    return 100.0 * passes / len(gold.EXACT_SYMBOL)


def _top5(search: SearchEngine) -> float:
    passes = 0
    for query, expected in gold.TOP5:
        ids = {r.entity_id for r in search.search(query, limit=5)}
        passes += 1 if expected in ids else 0
    return 100.0 * passes / len(gold.TOP5)


def _must_include(compiler: ContextCompiler) -> float:
    required = 0
    found = 0
    for intent, query, must, _ in gold.CONTEXT_CASES:
        ids = {i.entity_id for i in compiler.compile(intent, query).items}
        required += len(must)
        found += len(must & ids)
    return 100.0 * found / required if required else 100.0


def _irrelevant(compiler: ContextCompiler) -> float:
    total = 0
    irrelevant = 0
    for intent, query, must, allow in gold.CONTEXT_CASES:
        ids = [i.entity_id for i in compiler.compile(intent, query).items]
        total += len(ids)
        irrelevant += sum(1 for i in ids if i not in allow and i not in must)
    return 100.0 * irrelevant / total if total else 0.0
