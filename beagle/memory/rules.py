from __future__ import annotations

import hashlib
import logging

from ..llm.client import LLMClient
from ..prompts.loader import PromptSet
from ..storage.db import Database
from ..storage.migrations import utc_now

log = logging.getLogger("beagle.rules")
CONVENTIONS_BUDGET_TOKENS = 2000
STAMP_BLOCK = "conventions_block"
STAMP_SOURCE = "conventions_source"


class RuleStore:
    """The team's conventions, distilled into one block for the prompt."""

    def __init__(self, core: Database, client: LLMClient | None = None, prompts: PromptSet | None = None):
        self.core = core
        self.client = client
        self.prompts = prompts

    def add(self, body: str, author: str | None = None) -> dict:
        count = int(self.core.scalar("select count(*) from rules") or 0)
        rule_id = f"R{count + 1}"
        self.core.execute(
            "insert into rules (id, body, author, created_at) values (?,?,?,?)",
            (rule_id, body.strip(), author, utc_now()),
        )
        return {"id": rule_id, "body": body.strip(), "author": author}

    def remove(self, rule_id: str) -> None:
        self.core.execute("update rules set active = 0 where id = ?", (rule_id,))

    def active(self) -> list[dict]:
        rows = self.core.query(
            "select id, body, author, hits, created_at from rules where active = 1"
            " order by hits desc, id"
        )
        return [dict(row) for row in rows]

    def block(self) -> str:
        """Distilled again only when the rules change."""
        rules = self.active()
        if not rules:
            return ""
        signature = fingerprint(rules)
        if self.core.scalar("select value from config_stamps where key = ?", (STAMP_SOURCE,)) == signature:
            stored = self.core.scalar("select value from config_stamps where key = ?", (STAMP_BLOCK,))
            if stored:
                return stored
        block = self.distill(rules) or plain(rules)
        self.store(block, signature)
        return block

    def distill(self, rules: list[dict]) -> str | None:
        if self.client is None or self.prompts is None:
            return None
        prompt = self.prompts.get("distill").render({"budget": str(CONVENTIONS_BUDGET_TOKENS)})
        try:
            reply = self.client.send(
                {
                    "model": self.client.model_for("haiku"),
                    "max_tokens": 2000,
                    "system": [{"type": "text", "text": prompt}],
                    "messages": [{"role": "user", "content": table(rules)}],
                },
                prompt_name="distill",
            )
        except Exception as exc:
            log.warning("rule distillation failed, using the plain list: %s", exc)
            return None
        return reply.text.strip() or None

    def store(self, block: str, signature: str) -> None:
        for key, value in ((STAMP_BLOCK, block), (STAMP_SOURCE, signature)):
            self.core.execute(
                "insert into config_stamps (key, value, updated_at) values (?,?,?)"
                " on conflict(key) do update set value = excluded.value,"
                " updated_at = excluded.updated_at",
                (key, value, utc_now()),
            )


def table(rules: list[dict]) -> str:
    lines = ["id | rule | author | hits"]
    for rule in rules:
        lines.append(f"{rule['id']} | {rule['body']} | {rule.get('author') or '-'} | {rule['hits']}")
    return "\n".join(lines)


def plain(rules: list[dict]) -> str:
    return "TEAM CONVENTIONS — follow these over your own taste:\n" + "\n".join(
        f"{rule['id']}: {rule['body']}" for rule in rules
    )


def fingerprint(rules: list[dict]) -> str:
    seed = "|".join(f"{rule['id']}:{rule['body']}" for rule in rules)
    return hashlib.sha256(seed.encode()).hexdigest()[:16]
