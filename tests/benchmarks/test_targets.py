"""Gate the design/05 targets on the synthetic fixture.

Runs with the normal suite, so any extraction/resolution/retrieval regression
that drops a metric below target fails CI. Numbers are exact because the
fixture's ground truth is fully enumerated in benchmarks/gold.py.
"""

from __future__ import annotations

import pytest

from beagle.benchmarks.runner import run


@pytest.fixture(scope="module")
def result():
    return run()


def test_no_metric_regresses(result):
    report, _ = result
    failures = [f"{m.name}={m.value:.1f}% (target {m.target}%)" for m in report.metrics if not m.passed]
    assert not failures, "metrics below target: " + ", ".join(failures)


def test_no_stale_facts(result):
    report, _ = result
    assert report.stale_facts == 0


def test_inheritance_and_overrides_present(result):
    _, extras = result
    assert extras["inherits_overrides_found"] == extras["inherits_overrides_total"]


def test_overall_pass(result):
    report, _ = result
    assert report.passed
