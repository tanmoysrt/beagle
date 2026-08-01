from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from ..config import GithubCfg
from .client import GithubClient
from .events import FINDING_MARKER, Comment, command_text, skip_reason
from .state import SyncState

log = logging.getLogger("beagle.github.poller")

# A reaction is a weak signal next to a written reply, so it counts for less.
REACTION_WEIGHT = 0.3
REACTIONS = (("+1", "accept"), ("-1", "false_positive"))


@dataclass(frozen=True)
class Thumbs:
    comment_id: str
    fingerprint: str
    counts: list[int]


class Poller:
    """Watches pull requests and `@beagle` comments where webhooks are not set up."""

    def __init__(
        self,
        github: GithubClient,
        state: SyncState,
        cfg: GithubCfg,
        enqueue: Callable[[str, dict], int],
    ):
        self.github = github
        self.state = state
        self.cfg = cfg
        self.enqueue = enqueue
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.loop, name="beagle-github-poll", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=timeout)

    def loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("a github poll failed")
            self.stopping.wait(self.cfg.poll_interval_seconds)

    def tick(self) -> None:
        for number in self.scan_pulls():
            self.scan_comments(number)

    def scan_pulls(self) -> list[int]:
        """Queue a review for every pull request whose head Beagle has not seen."""
        pulls, etag = self.github.open_pulls(self.state.get("pulls_etag"))
        if pulls is None:
            return self.state.tracked_prs()
        self.state.set("pulls_etag", etag)

        open_numbers = []
        for pull in pulls:
            open_numbers.append(pull["number"])
            if self.wants_review(pull):
                self.enqueue("github_review", {"pr": pull["number"]})
        for number in self.state.tracked_prs():
            if number not in open_numbers:
                self.state.forget_pr(number)
        return open_numbers

    def wants_review(self, pull: dict) -> bool:
        number, head = pull["number"], pull["head"]["sha"]
        record = self.state.pr(number)
        if record.get("reviewed_sha") == head:
            return False
        reason = skip_reason(pull, self.cfg)
        if reason:
            log.info("skipping #%s (%s)", number, reason)
            return False
        event = "synchronize" if record.get("reviewed_sha") else "opened"
        if event not in self.cfg.review_on:
            return False
        # Claim the sha now: a review costs money and must not be queued twice.
        self.state.update_pr(number, reviewed_sha=head)
        return True

    def scan_comments(self, number: int) -> None:
        record = self.state.pr(number)
        issue = self.github.issue_comments(number)
        review = self.github.review_comments(number)
        thumbs = thumbs_on(issue + review)

        # On first sight, take the watermarks without acting: the history of a
        # pull request Beagle has never watched is not a queue of new commands.
        seen = record.get("reactions", {})
        if "issue_mark" in record:
            self.dispatch(number, issue, "issue", record.get("issue_mark", 0))
            self.dispatch(number, review, "review", record.get("review_mark", 0))
            self.claim_reactions(number, thumbs, seen)

        self.state.update_pr(
            number,
            # merged, so counts survive a comment falling outside the pages read
            reactions={**seen, **{thumb.comment_id: thumb.counts for thumb in thumbs}},
            issue_mark=highest_id(issue, record.get("issue_mark", 0)),
            review_mark=highest_id(review, record.get("review_mark", 0)),
        )

    def dispatch(self, number: int, comments: list[dict], kind: str, mark: int) -> None:
        """Queue every comment for Beagle that is newer than the watermark."""
        for comment in comments:
            if comment["id"] <= mark or command_text(comment.get("body") or "", self.cfg.mention) is None:
                continue
            log.info("queueing a %s comment on #%s from %s", kind, number,
                     (comment.get("user") or {}).get("login"))
            self.enqueue(
                "github_comment",
                Comment(
                    number=number,
                    id=comment["id"],
                    body=comment.get("body") or "",
                    author=(comment.get("user") or {}).get("login"),
                    kind=kind,
                    in_reply_to=comment.get("in_reply_to_id"),
                ).payload(),
            )

    def claim_reactions(self, number: int, thumbs: list[Thumbs], seen: dict) -> None:
        """A thumb on one of Beagle's finding comments is feedback about that finding."""
        for thumb in thumbs:
            before = seen.get(thumb.comment_id, [0] * len(REACTIONS))
            for index, (_, action) in enumerate(REACTIONS):
                if thumb.counts[index] > before[index]:
                    self.enqueue(
                        "github_feedback",
                        {
                            "pr": number,
                            "fingerprint": thumb.fingerprint,
                            "action": action,
                            "weight": REACTION_WEIGHT,
                        },
                    )


def thumbs_on(comments: list[dict]) -> list[Thumbs]:
    """Reaction counts on Beagle's own finding comments. Reads, never acts."""
    found = []
    for comment in comments:
        marker = FINDING_MARKER.search(comment.get("body") or "")
        if not marker:
            continue
        reactions = comment.get("reactions") or {}
        found.append(
            Thumbs(
                comment_id=str(comment["id"]),
                fingerprint=marker.group(1),
                counts=[reactions.get(name, 0) for name, _ in REACTIONS],
            )
        )
    return found


def highest_id(comments: list[dict], fallback: int) -> int:
    return max([comment["id"] for comment in comments], default=fallback)
