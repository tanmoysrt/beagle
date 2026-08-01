from __future__ import annotations

import json
from typing import Any

from ..constants import SCHEMA_VERSION


class Reporter:
    """Every question the server answers about itself. Reads only."""

    def __init__(self, service):
        self.service = service

    def review(self, review_id: str) -> dict[str, Any] | None:
        core = self.service.storage.core
        row = core.one("select * from reviews where id = ?", (review_id,))
        if row is None:
            return None
        findings = [
            finding_dict(item)
            for item in core.query(
                "select * from findings where review_id = ? order by severity, id", (review_id,)
            )
        ]
        return {
            "review_id": row["id"],
            "base_sha": row["base_sha"],
            "head_sha": row["head_sha"],
            "status": row["status"],
            "summary": json.loads(row["summary_json"]) if row["summary_json"] else {},
            "findings": [item for item in findings if item["status"] == "open"],
            "suppressed": [item for item in findings if item["status"] != "open"],
        }

    def index_status(self) -> dict[str, Any]:
        service = self.service
        status = service.indexer.status()
        status["vectors"] = service.vectors.counts()
        status["mirror_present"] = service.mirror.exists
        # a client matches this against its git remote to find the right server
        status["repo"] = service.config.repo.url
        status["default_base"] = service.config.repo.default_base
        return status

    def stats(self) -> dict[str, Any]:
        service = self.service
        core = service.storage.core
        return {
            "reviews": int(core.scalar("select count(*) from reviews") or 0),
            "findings": int(core.scalar("select count(*) from findings") or 0),
            "suppressed": int(
                core.scalar("select count(*) from findings where status = 'suppressed'") or 0
            ),
            "by_category": tally(core, "select category, count(*) from findings group by category"),
            "by_severity": tally(core, "select severity, count(*) from findings group by severity"),
            "feedback": tally(core, "select action, count(*) from feedback group by action"),
            "spend": self.spend(),
            "calibration": service.calibrator.report(),
            "rules": len(service.rules.active()),
            "index": service.store.counts(),
        }

    def spend(self) -> dict[str, Any]:
        llm_log = self.service.storage.llm_log
        totals = llm_log.one(
            "select coalesce(sum(cost_usd),0), coalesce(sum(tokens_in),0),"
            " coalesce(sum(tokens_out),0), coalesce(sum(tokens_cached),0), count(*) from llm_calls"
        )
        # embeddings never read the cache, so they would drag the rate down
        cache = llm_log.one(
            "select coalesce(sum(tokens_cached),0), coalesce(sum(tokens_in),0)"
            " from llm_calls where prompt_name is not null and prompt_name != 'embeddings'"
        )
        per_prompt = llm_log.query(
            "select prompt_name, count(*) as calls, round(sum(cost_usd),4) as cost,"
            " sum(tokens_cached) as cached from llm_calls"
            " where prompt_name is not null group by prompt_name order by cost desc"
        )
        return {
            "cost_usd": round(totals[0], 4),
            "tokens_in": totals[1],
            "tokens_out": totals[2],
            "tokens_cached": totals[3],
            "calls": totals[4],
            "cache_hit_rate": round(cache[0] / cache[1], 3) if cache[1] else 0.0,
            "by_prompt": [dict(row) for row in per_prompt],
        }

    def doctor(self) -> dict[str, Any]:
        service = self.service
        config = service.config
        return {
            "schema_version": SCHEMA_VERSION,
            "prompt_set": service.prompts.version(),
            "prompts": service.prompts.report(),
            "github": (
                f"enabled (repo {config.github.repo}, mode {config.github.mode})"
                if config.github_enabled
                else "disabled (no token)"
            ),
            "repo_access": config.repo_access_mode(),
            "config": [
                {"key": key, "value": value, "source": source}
                for key, value, source in service.provider.loaded.effective()
            ],
            "checks": self.checks(),
            "index": self.index_status(),
        }

    def checks(self) -> list[dict[str, Any]]:
        service = self.service
        found = []
        if service.github is not None:
            found.append(service.github.check())
        found.append(check("mirror", service.mirror.exists, str(service.mirror.path)))
        found.append(
            check(
                "index",
                service.indexer.indexed_sha is not None,
                str(service.indexer.indexed_sha),
            )
        )
        found.append(self.embeddings_check())
        found.append(self.cache_check())
        return found

    def embeddings_check(self) -> dict[str, Any]:
        """Ask the endpoint now, so a wrong width fails here and not mid-index."""
        pending = self.service.store.pending_chunk_count()
        try:
            width = self.service.embeddings.probe()
        except Exception as exc:
            return check("embeddings", False, str(exc))
        return check("embeddings", pending == 0, f"{width} dimensions, {pending} chunks pending")

    def cache_check(self) -> dict[str, Any]:
        """A cached prefix that never gets read means something is invalidating it."""
        row = self.service.storage.llm_log.one(
            "select count(*), coalesce(sum(tokens_cached),0) from llm_calls"
            " where prompt_name = 'reviewer'"
        )
        calls, cached = int(row[0] or 0), int(row[1] or 0)
        if calls < 2:
            return check("prompt cache", True, f"{calls} reviewer call(s), too early to judge")
        return check(
            "prompt cache",
            cached > 0,
            f"{cached} tokens read from cache across {calls} reviewer calls",
        )


def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def tally(core, sql: str) -> dict[str, int]:
    return {row[0]: row[1] for row in core.query(sql)}


def finding_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "fingerprint": row["fingerprint"],
        "file": row["file"],
        "line_start": row["line_start"],
        "line_end": row["line_end"],
        "category": row["category"],
        "severity": row["severity"],
        "model_severity": row["model_severity"],
        "app_code": None if row["app_code"] is None else bool(row["app_code"]),
        "confidence": row["confidence"],
        "title": row["title"],
        "body": row["body"],
        "suggested_patch": row["suggested_patch"],
        "status": row["status"],
        "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
    }
