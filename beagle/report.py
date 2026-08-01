from __future__ import annotations

from typing import Any

BADGES = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🔵", "P4": "⚪", "P5": "⚪"}


def render_markdown(review: dict[str, Any]) -> str:
    """The full report. The pull request summary reuses the same parts."""
    summary = review.get("summary", {})
    lines = verdict_block(summary) + [""]

    for finding in review.get("findings", []):
        if finding.get("status") in (None, "open"):
            lines += finding_block(finding)

    lines += notes_block(summary)
    lines += ["", f"_{cost_line(summary)}_"]
    return "\n".join(lines)


def verdict_block(summary: dict[str, Any]) -> list[str]:
    """Score, nudge, why, and where to look — in that order and nothing else."""
    lines = [f"### Confidence Score: {summary.get('score', 5)}/5", ""]
    if summary.get("description"):
        lines += [summary["description"], ""]
    if summary.get("reasoning"):
        lines += [summary["reasoning"], ""]
    attention = summary.get("attention") or []
    lines.append("\n".join(attention) if attention else "No files require special attention.")
    return lines


def notes_block(summary: dict[str, Any]) -> list[str]:
    """Everything said about the review as a whole rather than about one finding."""
    lines: list[str] = []
    if summary.get("overflow"):
        lines.append(f"_+{summary['overflow']} minor observations held back._")
    if summary.get("notes"):
        lines += ["", "**Notes:**"] + [f"- {note}" for note in summary["notes"]]
    if summary.get("skipped_files"):
        skipped = ", ".join(
            f"{item['path']} ({item['reason']})" for item in summary["skipped_files"]
        )
        lines += ["", f"Not reviewed: {skipped}"]
    if summary.get("degraded"):
        lines += ["", "Degraded: " + ", ".join(summary["degraded"])]
    return lines


def cost_line(summary: dict[str, Any]) -> str:
    return (
        f"${summary.get('cost_usd', 0):.4f} · "
        f"{summary.get('tokens_in', 0)} in / {summary.get('tokens_out', 0)} out "
        f"({summary.get('tokens_cached', 0)} cached) · {summary.get('duration_seconds', 0)}s"
    )


def finding_block(finding: dict[str, Any]) -> list[str]:
    badge = BADGES.get(finding["severity"], "")
    location = finding["file"]
    if finding.get("line_start"):
        location += f":{finding['line_start']}"
    lines = [
        f"### {badge} {finding['severity']} — {finding['title']}",
        f"`{location}` · {finding['category']} · confidence {finding['confidence']:.2f}",
        "",
        finding["body"],
    ]
    if finding.get("suggested_patch"):
        lines += ["", "```suggestion", finding["suggested_patch"], "```"]
    lines.append("")
    return lines
