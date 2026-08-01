from __future__ import annotations

import logging
import re

import json

from ..config import Severity
from ..errors import GithubError
from ..pipeline.models import (
    Finding,
    ReviewSummary,
    count_by_severity,
    score_for,
    verdict_for,
)
from ..pipeline.runner import ReviewResult
from ..report import BADGES, notes_block, usage_line, verdict_block
from .client import GithubClient
from .events import DEFAULT_MENTION, FINDING_MARKER, RESOLVED_MARKER, SUMMARY_MARKER

log = logging.getLogger("beagle.github.poster")

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
COMMENT_TITLE = re.compile(r"\*\*P\d — (.+?)\*\*")


class ReviewPoster:
    """Puts a review on a pull request and keeps it in step on a re-push.

    One comment holds the summary and is edited from then on, so the pull request
    never collects a second one. New findings ride out together in one review
    submission. A round that finds nothing new and changes no verdict posts
    nothing at all. Comments are matched by the hidden marker in their body rather
    than by a stored identifier, so the mapping survives a lost database.
    """

    def __init__(
        self,
        github: GithubClient,
        sync,
        service,
        style: str = "inline_plus_summary",
        mention: str = DEFAULT_MENTION,
    ):
        self.github = github
        self.sync = sync
        self.service = service
        self.inline = style == "inline_plus_summary"
        self.mention = mention

    @property
    def fail_on(self) -> Severity:
        return self.service.config.review.fail_on

    @property
    def model(self) -> str:
        """The model that read the code, so a reader knows what judged it."""
        return self.service.config.llm.models.reasoning

    def post(
        self, number: int, head_sha: str, result: ReviewResult, last_verdict: str | None = None
    ) -> dict:
        placed, resolved = self.scan(number)
        current = {finding.fingerprint: finding for finding in result.findings}
        fresh = [
            finding for fingerprint, finding in current.items() if fingerprint not in placed
        ]

        comments, unplaced = self.anchor(number, fresh)
        closing = {
            fingerprint: comment
            for fingerprint, comment in placed.items()
            if fingerprint not in current and fingerprint not in resolved
        }
        withdrawn = {item.fingerprint for item in result.suppressed + result.rejected}

        self.write_summary(number, render_summary(
            result.summary.to_dict(),
            unplaced,
            resolution_lines(closing, withdrawn, head_sha),
            self.mention,
            self.commit_note(head_sha),
            self.model,
        ))
        # A review with no line comment only repeats the summary in another place.
        # The one exception is asking for changes, which is a state, not a message.
        verdict = result.summary.verdict
        blocking = verdict == "request_changes" and verdict != last_verdict
        posted = bool(comments) or blocking
        if posted:
            self.submit(number, head_sha, verdict, result.summary.description, comments)
        return {
            "added": len(comments),
            "resolved": len(closing),
            "in_summary": len(unplaced),
            "review_posted": bool(posted),
        }

    def write_summary(self, number: int, body: str) -> None:
        """One summary comment for the life of the pull request, edited in place."""
        stored = self.sync.pr(number).get("summary_comment")
        if stored is None:
            stored = next(
                (item["id"] for item in self.github.issue_comments(number)
                 if SUMMARY_MARKER in (item.get("body") or "")),
                None,
            )
        try:
            if stored:
                self.github.update_issue_comment(stored, body)
            else:
                stored = self.github.create_issue_comment(number, body).get("id")
        except GithubError as exc:
            log.warning("could not write the summary on #%s: %s", number, exc)
            return
        self.sync.update_pr(number, summary_comment=stored)

    def summary_state(self, number: int):
        """The summary as posted, and the findings that still stand."""
        core = self.service.storage.core
        row = core.one(
            "select summary_json, head_sha from reviews where id = ?", (f"pr-{number}",)
        )
        if row is None or not row[0]:
            return None
        summary = ReviewSummary(**{
            key: value for key, value in json.loads(row[0]).items()
            if key in ReviewSummary.__dataclass_fields__
        })
        rows = core.query(
            "select file, line_start, line_end, category, severity, title, body, suggested_patch"
            " from findings where review_id = ? and status = 'open' order by severity",
            (f"pr-{number}",),
        )
        findings = [
            Finding(
                file=item[0], line_start=item[1], line_end=item[2], category=item[3],
                severity=Severity(item[4]), title=item[5], body=item[6], suggested_patch=item[7],
            )
            for item in rows
        ]
        return summary, findings, row[1]

    def commit_note(self, head_sha: str | None) -> str:
        """The commit the review looked at, named so a reader can place it."""
        if not head_sha:
            return ""
        try:
            subject = self.service.mirror.run(
                ["log", "-1", "--format=%s", head_sha]
            ).strip().splitlines()[0]
        except Exception:
            subject = ""
        short = head_sha[:7]
        return f"`{short}` {subject}" if subject else f"`{short}`"

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

    def anchor(self, number: int, findings: list[Finding]) -> tuple[list[dict], list[Finding]]:
        """A batched review is rejected whole, so an unanchorable finding must be
        moved to the summary before the request goes out, not after it fails."""
        if not self.inline:
            return [], list(findings)
        try:
            commentable = commentable_lines(self.github.pull_files(number))
        except GithubError as exc:
            log.warning("could not read the diff of #%s: %s", number, exc)
            return [], list(findings)

        comments, unplaced = [], []
        for finding in findings:
            payload = comment_payload(finding, commentable.get(finding.file, set()))
            if payload is None:
                unplaced.append(finding)
            else:
                comments.append(payload)
        return comments, unplaced

    def submit(
        self, number: int, head_sha: str, verdict: str, body: str, comments: list[dict]
    ) -> None:
        """The review carries the findings and the state. The summary lives elsewhere,
        so the body is only the one line GitHub needs for REQUEST_CHANGES."""
        event = "REQUEST_CHANGES" if verdict == "request_changes" else "COMMENT"
        body = body.strip() or "See the summary comment."
        for attempt in (event, "COMMENT"):
            try:
                self.github.submit_review(number, attempt, body, comments, head_sha)
                return
            except GithubError as exc:
                # GitHub refuses REQUEST_CHANGES on a pull request the token's own account opened.
                log.warning("review on #%s rejected as %s: %s", number, attempt, exc)
                comments = []  # a rejected batch must not post twice

    def refresh(self, number: int) -> None:
        """Rewrite the summary in place after a finding was withdrawn.

        The score and the counts described the review as it was posted. Once the
        author rejects a finding, that summary is wrong, and a new review would
        be a second notification for a correction.
        """
        state = self.summary_state(number)
        if state is None:
            return
        summary, findings, head_sha = state
        summary.score = score_for(findings, summary.coverage)
        summary.counts = count_by_severity(findings)
        summary.verdict = verdict_for(findings, self.fail_on)
        self.write_summary(number, render_summary(
            summary.to_dict(), [], [], self.mention, self.commit_note(head_sha), self.model
        ))


def comment_payload(finding: Finding, commentable: set[int]) -> dict | None:
    line = finding.line_end or finding.line_start
    if not line or line not in commentable:
        return None
    payload = {
        "body": finding_body(finding, inline=True),
        "path": finding.file,
        "side": "RIGHT",
        "line": line,
    }
    start = finding.line_start
    if start and start < line and start in commentable:
        payload["start_line"] = start
        payload["start_side"] = "RIGHT"
    return payload


def commentable_lines(files: list[dict]) -> dict[str, set[int]]:
    """The right-side lines GitHub will accept a comment on: those inside a hunk."""
    lines: dict[str, set[int]] = {}
    for entry in files:
        numbers: set[int] = set()
        cursor = 0
        for row in (entry.get("patch") or "").splitlines():
            header = HUNK_HEADER.match(row)
            if header:
                cursor = int(header.group(1))
            elif row.startswith(("+", " ")):
                numbers.add(cursor)
                cursor += 1
            elif not row.startswith("-"):
                cursor += 1
        lines[entry.get("filename", "")] = numbers
    return lines


def resolution_lines(closing: dict[str, dict], withdrawn: set[str], head_sha: str) -> list[str]:
    """Closed threads are reported once in the summary, not as a reply on each one."""
    lines = []
    for fingerprint, comment in closing.items():
        state = "withdrawn" if fingerprint in withdrawn else f"fixed in `{head_sha[:7]}`"
        title, url = title_of(comment), comment.get("html_url")
        lines.append(f"- {f'[{title}]({url})' if url else title} — {state}")
    return lines


def title_of(comment: dict) -> str:
    found = COMMENT_TITLE.search(comment.get("body") or "")
    return found.group(1) if found else "a finding"


def finding_body(finding: Finding, inline: bool) -> str:
    badge = BADGES.get(finding.severity.value, "")
    lines = [f"{badge} **{finding.severity.value} — {finding.title}**", "", finding.body]
    if not inline:
        lines.insert(0, f"`{location(finding)}`")
    patch = patch_block(finding, inline)
    if patch:
        lines += ["", patch]
    note = f"{finding.category} · confidence {finding.confidence:.0%}"
    if inline:
        # only a finding with a thread of its own can be answered
        lines += folded(finding)
        note += " · reply to this comment if it is wrong and I will remember"
    lines += ["", f"<sub>{note}</sub>", f"<!-- beagle:finding:{finding.fingerprint} -->"]
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


def folded(finding: Finding) -> list[str]:
    """The finding as plain text a coding agent can act on, folded away by default."""
    where = ", ".join(item.label() for item in finding.locations)
    brief = [
        "Fix this in the repository. Change nothing else.",
        "",
        f"{where} [{finding.severity.value} {finding.category}] {finding.title}",
        " ".join(finding.body.split()),
    ]
    if finding.suggested_patch:
        # verbatim: an added space would break the indentation of what it replaces
        brief.append("suggested replacement:")
        brief += finding.suggested_patch.rstrip().splitlines()
    return [
        "",
        "<details>",
        "<summary>Give this to a coding agent</summary>",
        "",
        "```",
        *brief,
        "```",
        "",
        "</details>",
    ]


def render_summary(
    summary: dict,
    unplaced: list[Finding],
    resolved: list[str],
    mention: str,
    commit: str = "",
    model: str = "",
) -> str:
    lines = verdict_block(summary)

    if unplaced:
        lines += [
            "",
            "**These are not on a changed line, so GitHub takes no comment there:**",
            "",
        ]
        for finding in unplaced:
            lines += [finding_body(finding, inline=False), ""]
    if resolved:
        lines += ["", "**Settled since the last review:**", ""] + resolved

    lines += notes_block(summary)
    if commit:
        lines += ["", f"Reviewed up to {commit}"]
    lines += [
        "",
        f"<sub>{usage_line(summary, model)} · `@{mention} review` to run again</sub>",
        SUMMARY_MARKER,
    ]
    return "\n".join(lines)
