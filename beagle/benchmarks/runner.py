"""Build the fixture, index it, and score it — plus the stale-facts check."""

from __future__ import annotations

import tempfile
from pathlib import Path

from beagle.benchmarks import gold
from beagle.benchmarks.fixture import write_fixture
from beagle.benchmarks.metrics import Report, score
from beagle.workspace import Workspace


def run() -> tuple[Report, dict]:
    """Index the fixture, score it, and verify incremental leaves no stale facts."""
    with tempfile.TemporaryDirectory() as tmp:
        root = write_fixture(Path(tmp))
        workspace = Workspace(root)
        workspace.index()
        report = score(workspace)
        report.stale_facts = _stale_facts_after_edit(workspace, root)
        extras = _inheritance_present(workspace)
        workspace.close()
    return report, extras


def _stale_facts_after_edit(workspace: Workspace, root: Path) -> int:
    """Remove a symbol from a file, reindex, and count facts that should be gone."""
    (root / "shop" / "utils.py").write_text("def slugify(value):\n    return value\n")
    workspace.index()
    repo = workspace.repo
    stale = 0
    # make_code was deleted: its entity and any edge naming it must be gone.
    if repo.get_entity("python://shop.utils#make_code") is not None:
        stale += 1
    rows = repo.conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE source_id=? OR target_id=?",
        ("python://shop.utils#make_code", "python://shop.utils#make_code"),
    ).fetchone()
    stale += rows["n"]
    return stale


def _inheritance_present(workspace: Workspace) -> dict:
    found = set()
    for source, rel, target in gold.INHERITS_OVERRIDES:
        for edge in workspace.repo.edges_from(source, (rel,)):
            if edge.target_id == target:
                found.add((source, rel, target))
    return {"inherits_overrides_found": len(found), "inherits_overrides_total": len(gold.INHERITS_OVERRIDES)}
