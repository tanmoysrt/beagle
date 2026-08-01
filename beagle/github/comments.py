from __future__ import annotations

import logging
import re

from ..pipeline.schemas import COMMENT_SCHEMA, OUTPUT_INSTRUCTIONS
from .client import GithubClient
from .events import FINDING_MARKER, Comment, command_text

log = logging.getLogger("beagle.github.comments")

COMMAND_HELP = [
    ("@beagle false positive [why]", "the finding is wrong, and Beagle should learn from it"),
    ("@beagle fp", "the same, in fewer words"),
    ("@beagle not now", "dismiss this one instance and learn nothing"),
    ("@beagle explain", "more detail about the finding in this thread"),
    ("@beagle rule: <text>", "record a team convention"),
    ("@beagle review", "review the pull request again"),
    ("@beagle review deep", "review again, strongest model on every file"),
    ("@beagle rules", "list the conventions"),
    ("@beagle status", "the condition of the index and the queue"),
    ("@beagle help", "this list"),
]

FAST_PATHS = (
    ("false_positive", re.compile(r"^(?:false[\s-]?positive|fp)\b[:,]?\s*(.*)", re.I | re.S)),
    ("dismiss", re.compile(r"^(?:not now|dismiss)\b[:,]?\s*(.*)", re.I | re.S)),
    ("rule", re.compile(r"^rule:\s*(.+)", re.I | re.S)),
    ("explain", re.compile(r"^explain\b\s*(.*)", re.I | re.S)),
    ("review_deep", re.compile(r"^review\s+deep\b", re.I)),
    ("review", re.compile(r"^review\b", re.I)),
    ("rules", re.compile(r"^rules\b", re.I)),
    ("status", re.compile(r"^status\b", re.I)),
    ("help", re.compile(r"^help\b", re.I)),
)


class CommentRouter:
    """Turns an `@beagle` comment into one of a fixed set of actions.

    Comment text only ever selects an action. It is never executed, and it never
    reaches the review prompt of this or any other pull request.
    """

    def __init__(self, github: GithubClient, service):
        self.github = github
        self.service = service

    def handle(self, comment: Comment) -> None:
        text = command_text(comment.body)
        if text is None:
            return
        fingerprint = self.thread_fingerprint(comment)
        action, argument = parse(text)
        if action is None:
            action, argument = self.classify(text, fingerprint)
        if action is None:
            log.info("ignoring comment %s on #%s", comment.id, comment.number)
            return
        self.act(comment, fingerprint, action, argument)

    def act(self, comment: Comment, fingerprint: str | None, action: str, argument: str) -> None:
        if action in ("false_positive", "dismiss"):
            self.feedback(comment, fingerprint, action, argument)
        elif action == "rule":
            self.add_rule(comment, fingerprint, argument)
        elif action == "explain":
            self.explain(comment, fingerprint, argument)
        elif action in ("review", "review_deep"):
            self.service.enqueue(
                "github_review", {"pr": comment.number, "deep": action == "review_deep"}
            )
            self.reply(comment, "On it. A new review is queued.")
        elif action == "rules":
            self.reply(comment, rules_block(self.service.rules.active()))
        elif action == "status":
            self.reply(comment, status_block(self.service.report.index_status()))
        elif action == "help":
            self.reply(comment, help_block())

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
                "model": self.service.llm.model_for("sonnet"),
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
            tier="haiku",
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


def help_block() -> str:
    lines = ["**What you can ask me**", "", "| command | meaning |", "| --- | --- |"]
    lines += [f"| `{command}` | {meaning} |" for command, meaning in COMMAND_HELP]
    lines.append("")
    lines.append("👍 on one of my comments counts as agreement, 👎 as a false positive.")
    return "\n".join(lines)


def rules_block(rules: list[dict]) -> str:
    if not rules:
        return "No conventions recorded yet. Add one with `@beagle rule: <text>`."
    lines = ["**Team conventions**", "", "| id | rule | hits |", "| --- | --- | --- |"]
    lines += [f"| {rule['id']} | {rule['body']} | {rule['hits']} |" for rule in rules]
    return "\n".join(lines)


def status_block(status: dict) -> str:
    return (
        f"Indexed commit `{str(status.get('sha') or 'none')[:7]}` · "
        f"{status.get('files', 0)} files · {status.get('symbols', 0)} symbols · "
        f"{status.get('pending_embeddings', 0)} chunks waiting for an embedding."
    )
