from __future__ import annotations

import logging

from ..errors import GithubError
from ..pipeline.models import Finding
from ..pipeline.runner import ReviewResult
from ..report import BADGES, cost_line, counts_line, notes_block, render_markdown, verdict_line
from .client import GithubClient
from .events import FINDING_MARKER, RESOLVED_MARKER, SUMMARY_MARKER

log = logging.getLogger("beagle.github.poster")


class ReviewPoster:
    """Puts a review on a pull request and keeps it in step on a re-push.

    Comments are matched by the hidden marker in their body rather than by a
    stored identifier, so the mapping survives a lost database.
    """

    def __init__(self, github: GithubClient, style: str = "inline_plus_summary"):
        self.github = github
        self.inline = style == "inline_plus_summary"

    def post(
        self, number: int, head_sha: str, result: ReviewResult, last_verdict: str | None = None
    ) -> dict:
        placed, resolved = self.scan(number)
        current = {finding.fingerprint: finding for finding in result.findings}

        added, unplaced = 0, []
        for fingerprint, finding in current.items():
            if fingerprint in placed:
                continue
            if self.inline and self.post_inline(number, head_sha, finding):
                added += 1
            else:
                unplaced.append(finding)

        closing = {
            fingerprint: comment
            for fingerprint, comment in placed.items()
            if fingerprint not in current and fingerprint not in resolved
        }
        withdrawn = {item.fingerprint for item in result.suppressed + result.rejected}
        closed = self.close_threads(number, closing, withdrawn, head_sha)
        self.write_summary(number, result, unplaced)
        if result.summary.verdict != last_verdict:
            self.submit_verdict(number, result.summary.verdict)
        return {"added": added, "resolved": closed, "in_summary": len(unplaced)}

    def scan(self, number: int) -> tuple[dict[str, dict], set[str]]:
        """Beagle's own finding comments, and the ones already called resolved."""
        placed, resolved = {}, set()
        for comment in self.github.review_comments(number):
            body = comment.get("body") or ""
            found = FINDING_MARKER.search(body)
            if found:
                placed[found.group(1)] = comment
            done = RESOLVED_MARKER.search(body)
            if done:
                resolved.add(done.group(1))
        return placed, resolved

    def post_inline(self, number: int, head_sha: str, finding: Finding) -> bool:
        """False when GitHub will not anchor the comment, so it goes in the summary."""
        if not finding.line_start:
            return False
        payload = {
            "body": finding_body(finding, inline=True),
            "commit_id": head_sha,
            "path": finding.file,
            "side": "RIGHT",
            "line": finding.line_end or finding.line_start,
        }
        if finding.line_end and finding.line_end > finding.line_start:
            payload["start_line"] = finding.line_start
            payload["start_side"] = "RIGHT"
        try:
            self.github.create_review_comment(number, payload)
            return True
        except GithubError as exc:
            log.info("inline comment on %s rejected, moving it to the summary: %s", finding.file, exc)
            return False

    def close_threads(
        self, number: int, closing: dict[str, dict], withdrawn: set[str], head_sha: str
    ) -> int:
        """Say why each thread is closing: the author fixed it, or Beagle withdrew it."""
        closed = 0
        for fingerprint, comment in closing.items():
            note = (
                "✔ Withdrawn. This is not a problem here."
                if fingerprint in withdrawn
                else f"✔ Resolved in `{head_sha[:7]}`."
            )
            body = f"{note}\n<!-- beagle:resolved:{fingerprint} -->"
            try:
                self.github.reply_to_review_comment(number, comment["id"], body)
                closed += 1
            except GithubError as exc:
                log.warning("could not close thread %s: %s", comment["id"], exc)
        return closed

    def write_summary(self, number: int, result: ReviewResult, unplaced: list[Finding]) -> None:
        body = summary_body(result, unplaced) if self.inline else full_report(result)
        existing = next(
            (
                comment
                for comment in self.github.issue_comments(number)
                if SUMMARY_MARKER in (comment.get("body") or "")
            ),
            None,
        )
        if existing:
            self.github.update_issue_comment(existing["id"], body)
        else:
            self.github.create_issue_comment(number, body)

    def submit_verdict(self, number: int, verdict: str) -> None:
        event = "REQUEST_CHANGES" if verdict == "request_changes" else "COMMENT"
        note = (
            "Beagle found something that should not merge as it stands."
            if event == "REQUEST_CHANGES"
            else "Beagle finished its review."
        )
        try:
            self.github.submit_review(number, event, f"{note} See the summary comment.")
        except GithubError as exc:
            # GitHub refuses REQUEST_CHANGES on a pull request the token's own account opened.
            log.warning("could not set the review state on #%s: %s", number, exc)


def finding_body(finding: Finding, inline: bool) -> str:
    badge = BADGES.get(finding.severity.value, "")
    lines = [f"{badge} **{finding.severity.value} — {finding.title}**", "", finding.body]
    if not inline:
        lines.insert(0, f"`{location(finding)}`")
    patch = patch_block(finding, inline)
    if patch:
        lines += ["", patch]
    lines += [
        "",
        f"_{finding.category} · confidence {finding.confidence:.0%} · "
        "reply `@beagle fp` if this is wrong_",
        f"<!-- beagle:finding:{finding.fingerprint} -->",
    ]
    return "\n".join(lines)


def patch_block(finding: Finding, inline: bool) -> str:
    if not finding.suggested_patch:
        return ""
    fence = "suggestion" if inline and replaces_cited_lines(finding) else ""
    return f"```{fence}\n{finding.suggested_patch.rstrip()}\n```"


def replaces_cited_lines(finding: Finding) -> bool:
    """A suggestion block replaces the whole commented range, so the shapes must agree."""
    if not finding.line_start:
        return False
    end = finding.line_end or finding.line_start
    return len(finding.suggested_patch.splitlines()) == end - finding.line_start + 1


def location(finding: Finding) -> str:
    if not finding.line_start:
        return finding.file
    return f"{finding.file}:{finding.line_start}"


def summary_body(result: ReviewResult, unplaced: list[Finding]) -> str:
    """The same summary as the report, plus what only a pull request needs."""
    summary = result.summary.to_dict()
    lines = ["## 🐕 Beagle review", ""]
    if summary["description"]:
        lines += [summary["description"], ""]
    lines += [verdict_line(summary), counts_line(summary)]
    if summary["suppressed"]:
        lines.append(f"{summary['suppressed']} finding(s) held back by what the team taught Beagle.")

    if unplaced:
        lines += ["", "These could not be anchored to a line in the diff:", ""]
        for finding in unplaced:
            lines += [finding_body(finding, inline=False), ""]

    lines += notes_block(summary)
    lines += ["", cost_line(summary), "", "_`@beagle help` for what you can ask._", SUMMARY_MARKER]
    return "\n".join(lines)


def full_report(result: ReviewResult) -> str:
    return render_markdown(result.to_dict()) + f"\n{SUMMARY_MARKER}"
