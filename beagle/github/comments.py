from __future__ import annotations

import logging
import re

from ..pipeline.schemas import COMMENT_SCHEMA, OUTPUT_INSTRUCTIONS
from .client import GithubClient
from .events import DEFAULT_MENTION, FINDING_MARKER, Comment, command_text

log = logging.getLogger("beagle.github.comments")

COMMAND_HELP = [
    ("review", "review the pull request again"),
    ("explain", "more detail about the finding in this thread"),
]

# Only the two verbs that must not be guessed at. Everything else a person
# writes is ordinary English and goes to the classifier.
FAST_PATHS = (
    ("explain", re.compile(r"^explain\b\s*(.*)", re.I | re.S)),
    ("review", re.compile(r"^review\b", re.I)),
)


class CommentRouter:
    """Turns an `@beagle` comment into one of a fixed set of actions.

    Comment text only ever selects an action. It is never executed, and it never
    reaches the review prompt of this or any other pull request.
    """

    def __init__(self, github: GithubClient, sync, service, mention: str = DEFAULT_MENTION):
        self.github = github
        self.sync = sync
        self.service = service
        self.mention = mention

    def handle(self, comment: Comment) -> None:
        text = command_text(comment.body, self.mention)
        if text is None:
            return
        self.ack(comment)
        fingerprint = self.thread_fingerprint(comment)
        action, argument = parse(text)
        if action is None:
            action, argument = self.classify(text, fingerprint)
        if action is None:
            log.info("ignoring comment %s on #%s", comment.id, comment.number)
            self.done(comment.number)
            return
        self.act(comment, fingerprint, action, argument)
        # a review runs as its own job and reports when it posts
        if action != "review":
            self.done(comment.number)

    def ack(self, comment: Comment) -> None:
        """A thumb on the comment Beagle read, an eye on the pull request while it works."""
        kind = "issues" if comment.kind == "issue" else "pulls"
        self.react(f"/{kind}/comments/{comment.id}", "+1")
        eyes = self.react(f"/issues/{comment.number}", "eyes")
        if eyes:
            self.sync.update_pr(comment.number, eyes=eyes)

    def done(self, number: int) -> None:
        eyes = self.sync.pr(number).get("eyes")
        if eyes:
            try:
                self.github.unreact(f"/issues/{number}", eyes)
            except Exception as exc:
                log.warning("could not remove the eye on #%s: %s", number, exc)
            self.sync.update_pr(number, eyes=None)
            self.react(f"/issues/{number}", "+1")

    def react(self, path: str, content: str) -> int | None:
        try:
            return self.github.react(path, content)
        except Exception as exc:
            log.warning("could not react %s on %s: %s", content, path, exc)
            return None

    def act(self, comment: Comment, fingerprint: str | None, action: str, argument: str) -> None:
        if action in ("false_positive", "dismiss"):
            self.feedback(comment, fingerprint, action, argument)
        elif action == "rule":
            self.add_rule(comment, fingerprint, argument)
        elif action == "explain":
            self.explain(comment, fingerprint, argument)
        elif action == "review":
            # the 👀 on the pull request is the acknowledgement; a reply would be a
            # second notification for the same thing
            self.service.enqueue("github_review", {"pr": comment.number})

    def feedback(self, comment: Comment, fingerprint: str | None, action: str, reason: str) -> None:
        finding = self.finding_for(comment.number, fingerprint)
        if finding is None:
            self.reply(comment, "Reply inside a finding thread and I will know what you mean.")
            return
        self.service.record_feedback(finding["id"], action, reason or None, comment.author)
        if action == "false_positive":
            self.reply(comment, "Understood. I will hold back findings like this one.")
        else:
            self.reply(comment, "Dropped for this change only.")

    def add_rule(self, comment: Comment, fingerprint: str | None, body: str) -> None:
        if not body.strip():
            return
        finding = self.finding_for(comment.number, fingerprint)
        if finding is not None:
            rule = self.service.record_feedback(
                finding["id"], "style_rule", body.strip(), comment.author
            )
        else:
            rule = self.service.rules.add(body.strip(), comment.author)
        self.reply(comment, f"Recorded as {rule['id']}: {rule['body']}")

    def explain(self, comment: Comment, fingerprint: str | None, question: str) -> None:
        finding = self.finding_for(comment.number, fingerprint)
        if finding is None:
            self.reply(comment, "Reply inside a finding thread and I will explain that finding.")
            return
        prompt = self.service.prompts.get("explain").render({})
        request = (
            f"FINDING ({finding['severity']} {finding['category']}) in {finding['file']}\n"
            f"{finding['title']}\n\n{finding['body']}\n\n"
            f"QUESTION FROM {comment.author or 'a reviewer'}:\n{question or 'Explain this.'}"
        )
        reply = self.service.llm.send(
            {
                "model": self.service.llm.model_for("general"),
                "max_tokens": 800,
                "system": [{"type": "text", "text": prompt}],
                "messages": [{"role": "user", "content": request}],
            },
            prompt_name="explain",
            review_id=f"pr-{comment.number}",
        )
        self.reply(comment, reply.text.strip() or "I have nothing to add.")

    def classify(self, text: str, fingerprint: str | None) -> tuple[str | None, str]:
        """Free-form text becomes one of four intents, or nothing at all."""
        prompt = self.service.prompts.get("comment_classifier").render(
            {"output_instructions": OUTPUT_INSTRUCTIONS["comment_classifier"]}
        )
        context = "REPLY TO A FINDING" if fingerprint else "TOP-LEVEL COMMENT"
        reply = self.service.llm.structured(
            tier="general",
            system=[{"type": "text", "text": prompt}],
            user=f"{context}\n\nCOMMENT:\n{text}",
            schema=COMMENT_SCHEMA,
            tool_name="classify_comment",
            max_tokens=500,
            prompt_name="comment_classifier",
        )
        intent = reply.data.get("intent")
        if intent == "false_positive":
            return "false_positive", reply.data.get("reason") or text
        if intent == "dismiss":
            return "dismiss", reply.data.get("reason") or text
        if intent == "style_rule":
            return "rule", reply.data.get("rule") or text
        if intent == "question":
            return "explain", text
        return None, ""

    def thread_fingerprint(self, comment: Comment) -> str | None:
        """A reply carries no finding of its own; the head of the thread does."""
        if comment.kind != "review":
            return None
        head = comment.in_reply_to or comment.id
        try:
            parent = self.github.review_comment(head)
        except Exception as exc:
            log.warning("could not read comment %s: %s", head, exc)
            return None
        found = FINDING_MARKER.search(parent.get("body") or "")
        return found.group(1) if found else None

    def finding_for(self, number: int, fingerprint: str | None) -> dict | None:
        if not fingerprint:
            return None
        row = self.service.storage.core.one(
            "select id, title, body, file, severity, category from findings"
            " where fingerprint = ? and review_id = ?",
            (fingerprint, f"pr-{number}"),
        )
        return dict(row) if row else None

    def reply(self, comment: Comment, body: str) -> None:
        text = f"{body}\n<!-- beagle:reply -->"
        if comment.kind == "review":
            self.github.reply_to_review_comment(
                comment.number, comment.in_reply_to or comment.id, text
            )
        else:
            self.github.create_issue_comment(comment.number, text)


def parse(text: str) -> tuple[str | None, str]:
    for action, pattern in FAST_PATHS:
        found = pattern.match(text)
        if found:
            return action, (found.group(1).strip() if found.groups() else "")
    return None, ""


