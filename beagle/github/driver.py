from __future__ import annotations

import logging
from typing import Any

from ..config import GithubCfg
from ..errors import BeagleError
from ..pipeline.runner import ReviewRequest
from ..storage.migrations import utc_now
from .client import GithubClient
from .comments import CommentRouter
from .events import Comment
from .poller import Poller
from .poster import ReviewPoster
from .state import SyncState

log = logging.getLogger("beagle.github")


class GithubDriver:
    """Everything the server does with GitHub, held in one place.

    The rest of the service keeps one attribute and asks it nothing about how
    GitHub is reached, or whether polling or a webhook brought the work in.
    """

    def __init__(self, cfg: GithubCfg, service):
        self.service = service
        self.client = GithubClient(cfg)
        self.sync = SyncState(service.storage.core)
        self.poster = ReviewPoster(self.client, cfg.post_style, cfg.mention)
        self.comments = CommentRouter(self.client, self.sync, service, cfg.mention)
        self.poller = (
            Poller(self.client, self.sync, cfg, service.enqueue) if cfg.mode == "poll" else None
        )

    def start(self) -> None:
        if self.poller is not None:
            self.poller.start()
            log.info("polling github every %ds", self.poller.cfg.poll_interval_seconds)

    def stop(self) -> None:
        if self.poller is not None:
            self.poller.stop()

    def handle(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "github_review":
            self.review(payload["pr"], payload.get("deep", False), payload.get("fresh", False))
        elif kind == "github_comment":
            self.comments.handle(Comment(**payload))
        elif kind == "github_feedback":
            self.reaction(payload)
        else:
            raise BeagleError(f"unknown job kind: {kind}")

    def review(self, number: int, deep: bool = False, fresh: bool = False) -> dict[str, Any]:
        pull = self.client.pull(number)
        if not self.service.mirror.exists:
            self.service.mirror.ensure()
        head_sha = self.service.mirror.fetch_pr(number)
        base = pull["base"]["ref"]
        request = ReviewRequest(
            review_id=f"pr-{number}",
            base=base,
            head=head_sha,
            # The index follows the base branch: one index for the repository,
            # never one for each pull request.
            index_ref=base,
            author=(pull.get("user") or {}).get("login"),
            deep=deep,
            fresh=fresh,
        )
        result = self.service.run(request)
        posted = self.poster.post(
            number, head_sha, result, self.sync.pr(number).get("verdict")
        )
        self.sync.update_pr(
            number,
            reviewed_sha=head_sha,
            verdict=result.summary.verdict,
            posted_at=utc_now(),
        )
        self.comments.done(number)
        log.info("posted review of #%s: %s", number, posted)
        return posted

    def reaction(self, payload: dict[str, Any]) -> None:
        row = self.service.storage.core.one(
            "select id from findings where fingerprint = ? and review_id = ?",
            (payload["fingerprint"], f"pr-{payload['pr']}"),
        )
        if row is None:
            return
        self.service.record_feedback(
            row[0], payload["action"], "reaction", None, payload["weight"]
        )

    def check(self) -> dict[str, Any]:
        """A token that cannot reach the repository is better found here than at the first push.

        Beagle never pushes. It reads the repository and writes comments, and a
        comment on a repository you can read needs no collaborator role.
        """
        try:
            info = self.client.repo_info()
        except Exception as exc:
            return {"name": "github", "ok": False, "detail": str(exc)}
        return {
            "name": "github",
            "ok": True,
            "detail": f"{info.get('full_name')}, {'private' if info.get('private') else 'public'}",
        }

    def close(self) -> None:
        self.client.close()
