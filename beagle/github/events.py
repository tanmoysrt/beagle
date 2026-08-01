from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import asdict, dataclass
from functools import lru_cache

from ..config import GithubCfg

MARKER = "<!-- beagle:"
SUMMARY_MARKER = "<!-- beagle:summary -->"
FINDING_MARKER = re.compile(r"<!-- beagle:finding:([0-9a-f]{32}) -->")
RESOLVED_MARKER = re.compile(r"<!-- beagle:resolved:([0-9a-f]{32}) -->")
DEFAULT_MENTION = "beagle"


@dataclass
class Comment:
    """One `@beagle` comment, from a webhook or from the poller."""

    number: int
    id: int
    body: str
    author: str | None = None
    kind: str = "issue"
    in_reply_to: int | None = None

    def payload(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=8)
def mention_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"@{re.escape(name)}(?![\w-])", re.I)


def command_text(body: str, mention: str = DEFAULT_MENTION) -> str | None:
    """What the author asked of Beagle, or None if the comment is not for Beagle."""
    if MARKER in body:
        return None
    found = mention_pattern(mention).search(body)
    return body[found.end():].strip() if found else None


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def skip_reason(pull: dict, cfg: GithubCfg) -> str | None:
    if pull.get("draft"):
        return "draft"
    if not cfg.review_forks:
        # a deleted head repository gives no name, so it counts as a fork
        origin = (pull.get("head") or {}).get("repo") or {}
        if origin.get("full_name") != cfg.repo:
            return "fork"
    return None


def job_for(event: str, payload: dict, cfg: GithubCfg) -> tuple[str, dict] | None:
    """Map a webhook delivery onto a queue job, or None to ignore it."""
    origin = (payload.get("repository") or {}).get("full_name")
    if origin != cfg.repo:
        return None

    if event == "pull_request":
        pull = payload.get("pull_request") or {}
        if payload.get("action") not in cfg.review_on or skip_reason(pull, cfg):
            return None
        return "github_review", {"pr": pull["number"]}

    if event == "issue_comment":
        issue = payload.get("issue") or {}
        if payload.get("action") != "created" or "pull_request" not in issue:
            return None
        return comment_job(issue.get("number"), payload.get("comment") or {}, "issue", cfg.mention)

    if event == "pull_request_review_comment":
        if payload.get("action") != "created":
            return None
        pull = payload.get("pull_request") or {}
        return comment_job(pull.get("number"), payload.get("comment") or {}, "review", cfg.mention)

    return None


def comment_job(number: int | None, raw: dict, kind: str, mention: str) -> tuple[str, dict] | None:
    body = raw.get("body") or ""
    if number is None or command_text(body, mention) is None:
        return None
    comment = Comment(
        number=number,
        id=raw.get("id", 0),
        body=body,
        author=(raw.get("user") or {}).get("login"),
        kind=kind,
        in_reply_to=raw.get("in_reply_to_id"),
    )
    return "github_comment", comment.payload()
