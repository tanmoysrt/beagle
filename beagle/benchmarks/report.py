"""Human-readable benchmark report. Exits non-zero if any target is missed.

    uv run python -m beagle.benchmarks.report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from beagle.benchmarks.runner import run
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

_CASES_FILE = Path(__file__).with_name("press_cases.json")


def main() -> int:
    # With a path argument, evaluate the real-repo retrieval cases against an
    # existing index (non-gating). With no argument, gate the synthetic fixture.
    if len(sys.argv) > 1:
        return _external(Path(sys.argv[1]))
    report, extras = run()
    print(f"{'metric':<20} {'value':>8} {'target':>8}  result")
    print("-" * 48)
    for m in report.metrics:
        cmp = "<=" if not m.higher_is_better else ">="
        print(f"{m.name:<20} {m.value:>7.1f}% {cmp}{m.target:>6.1f}%  {'PASS' if m.passed else 'FAIL'}")
    stale_ok = report.stale_facts == 0
    print(f"{'stale_facts':<20} {report.stale_facts:>8} {'== 0':>8}  {'PASS' if stale_ok else 'FAIL'}")
    print(f"\ninheritance/overrides found: "
          f"{extras['inherits_overrides_found']}/{extras['inherits_overrides_total']}")
    print(f"\noverall: {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


def _external(root: Path) -> int:
    cases = json.loads(_CASES_FILE.read_text())
    workspace = Workspace.locate(root)
    graph = GraphService(workspace.repo)
    search = SearchEngine(workspace.db)
    failures: list[str] = []

    for query, expected in cases.get("exact_symbol", []):
        if expected not in {e.id for e in graph.resolve(query)}:
            failures.append(f"exact_symbol: {query!r} -> {expected}")
    for query, expected in cases.get("top5", []):
        if expected not in {r.entity_id for r in search.search(query, limit=5)}:
            failures.append(f"top5: {query!r} -> {expected}")
    for source, rel, target in cases.get("edge_exists", []):
        if not any(e.target_id == target for e in workspace.repo.edges_from(source, (rel,))):
            failures.append(f"edge: {source} -{rel}-> {target}")

    total = sum(len(cases.get(k, [])) for k in ("exact_symbol", "top5", "edge_exists"))
    passed = total - len(failures)
    print(f"press retrieval cases: {passed}/{total} passed (root={workspace.root})")
    for f in failures:
        print(f"  FAIL {f}")
    workspace.close()
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
