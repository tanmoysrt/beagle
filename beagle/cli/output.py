from __future__ import annotations

import sys
from pathlib import Path

from ..server.service import BeagleService


def read_diff(source: str | None) -> str | None:
    if not source:
        return None
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def print_review(result) -> None:
    summary = result.summary
    print(f"\n{summary.verdict.upper()}  confidence {summary.confidence:.2f}  "
          f"coverage {summary.coverage:.0%}")
    if summary.description:
        print(f"\n{summary.description}")
    print()
    for finding in result.findings:
        locations = ", ".join(location.label() for location in finding.locations)
        print(f"[{finding.severity.value}] {locations}  ({finding.category}, "
              f"confidence {finding.confidence:.2f})")
        print(f"      {finding.title}")
        for line in finding.body.splitlines():
            print(f"        {line}")
        print()
    counts = ", ".join(f"{level} x{count}" for level, count in summary.counts.items() if count)
    print(f"{counts or 'no findings'}  ·  ${summary.cost_usd:.4f}  ·  {summary.duration_seconds}s")
    if summary.overflow:
        print(f"+{summary.overflow} minor observations not shown")
    for note in summary.notes:
        print(f"note: {note}")
    for item in summary.degraded:
        print(f"degraded: {item}")


def print_doctor(report: dict) -> None:
    print(f"prompt set : {report['prompt_set']}")
    print(f"github     : {report['github']}")
    print(f"repo access: {report['repo_access']}")
    print("\nchecks:")
    for check in report["checks"]:
        mark = "ok " if check["ok"] else "!! "
        print(f"  {mark} {check['name']:<12} {check['detail']}")
    print("\nprompts:")
    for prompt in report["prompts"]:
        print(f"  {prompt['name']:<20} {prompt['source']:<24} {prompt['digest']}")
    print("\neffective config:")
    for row in report["config"]:
        source = "default" if row["source"] == "default" else "config.toml"
        print(f"  {row['key']:<36} {row['value']:<34} <- {source}")


def print_eval(summary: dict) -> None:
    print(f"\n{summary['passed']}/{summary['cases']} cases passed  ·  "
          f"recall {summary['recall']:.0%}  ·  "
          f"{summary['false_positives']} false positives  ·  "
          f"{summary['extra_findings_per_case']} extra findings per case  ·  "
          f"${summary['cost_usd']}\n")
    if summary.get("degraded_cases"):
        print(f"!! {summary['degraded_cases']} case(s) did not finish, so the score is not one:")
        for note in summary.get("degraded", []):
            print(f"     {note}")
        print()
    for case in summary["detail"]:
        print(f"  {'pass' if case['passed'] else 'FAIL'}  {case['id']}")
        for line in case["missed"]:
            print(f"        missed    {line}")
        for line in case["forbidden_hits"]:
            print(f"        forbidden {line}")
        for line in case["severity_errors"]:
            print(f"        severity  {line}")
        for line in case["found"]:
            print(f"        found     {line}")


def exit_code_for(result, service: BeagleService) -> int:
    fail_on = service.config.review.fail_on
    return 1 if any(item.severity.at_least(fail_on) for item in result.findings) else 0
