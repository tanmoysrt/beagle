from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..constants import SCHEMA_VERSION
from ..github.events import job_for, verify_signature
from .auth import require_token
from .guide import guide_text
from ..report import render_markdown

router = APIRouter(prefix="/v1")


class ReviewBody(BaseModel):
    review_id: str | None = None
    base: str | None = None
    head: str | None = None
    diff: str | None = None
    author: str | None = None
    pr: int | None = None
    fresh: bool = False


class FeedbackBody(BaseModel):
    action: str = Field(pattern="^(accept|false_positive|dismiss|style_rule)$")
    reason: str | None = None
    author: str | None = None
    weight: float = 1.0


class RuleBody(BaseModel):
    body: str
    author: str | None = None


def service(request: Request):
    return request.app.state.service


def queue(request: Request):
    return request.app.state.queue


@router.post("/reviews", status_code=202)
def submit_review(body: ReviewBody, request: Request, token: str = Depends(require_token)):
    if body.pr is not None:
        if not service(request).config.github_enabled:
            raise HTTPException(status_code=409, detail="github integration is disabled")
        review_id = f"pr-{body.pr}"
        service(request).events.reset(review_id)
        job_id = queue(request).enqueue(
            "github_review", {"pr": body.pr, "fresh": body.fresh}, review_id
        )
    else:
        review_id = body.review_id or f"rev-{uuid.uuid4().hex[:12]}"
        payload = body.model_dump()
        payload["review_id"] = review_id
        # Clear the old run now, not when the worker starts: a client that reads
        # the stream immediately must not be handed the previous result.
        service(request).events.reset(review_id)
        job_id = queue(request).enqueue("review", payload, review_id)
    return {"review_id": review_id, "job_id": job_id, "schema_version": SCHEMA_VERSION}


@router.get("/reviews/{review_id}/stream")
def stream_review(review_id: str, request: Request, token: str = Depends(require_token)):
    stream = service(request).events.stream_for(review_id)

    def lines() -> Iterator[str]:
        try:
            for event in stream.subscribe():
                yield event.line() + "\n"
        except Exception as exc:
            yield json.dumps({"event": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.get("/reviews/{review_id}")
def get_review(review_id: str, request: Request, token: str = Depends(require_token)):
    result = service(request).report.review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no review {review_id}")
    return result


@router.get("/reviews/{review_id}/report")
def get_report(
    review_id: str, request: Request, format: str = "json", token: str = Depends(require_token)
):
    result = service(request).report.review(review_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no review {review_id}")
    if format == "md":
        return PlainTextResponse(render_markdown(result))
    return result


@router.post("/findings/{finding_id}/feedback")
def add_feedback(
    finding_id: str, body: FeedbackBody, request: Request, token: str = Depends(require_token)
):
    beagle = service(request)
    if beagle.storage.core.one("select 1 from findings where id = ?", (finding_id,)) is None:
        raise HTTPException(status_code=404, detail=f"no finding {finding_id}")
    rule = beagle.record_feedback(
        finding_id, body.action, body.reason, body.author, body.weight
    )
    return {"ok": True, "finding_id": finding_id, "action": body.action, "rule": rule}


@router.post("/feedback/batch")
def add_feedback_batch(
    items: list[dict[str, Any]], request: Request, token: str = Depends(require_token)
):
    beagle = service(request)
    accepted = 0
    for item in items:
        finding_id = item.get("finding_id")
        if beagle.storage.core.one("select 1 from findings where id = ?", (finding_id,)) is None:
            continue
        body = FeedbackBody(**{
            key: value for key, value in item.items() if key in FeedbackBody.model_fields
        })
        beagle.record_feedback(finding_id, body.action, body.reason, body.author, body.weight)
        accepted += 1
    return {"accepted": accepted, "received": len(items)}


@router.get("/rules")
def list_rules(request: Request, token: str = Depends(require_token)):
    return {"rules": service(request).rules.active()}


@router.post("/rules", status_code=201)
def add_rule(body: RuleBody, request: Request, token: str = Depends(require_token)):
    return service(request).rules.add(body.body, body.author)


@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: str, request: Request, token: str = Depends(require_token)):
    service(request).rules.remove(rule_id)
    return {"ok": True, "id": rule_id}


@router.get("/stats")
def stats(request: Request, token: str = Depends(require_token)):
    return service(request).report.stats()


@router.post("/index/rebuild", status_code=202)
def rebuild_index(request: Request, full: bool = False, token: str = Depends(require_token)):
    job_id = queue(request).enqueue("index", {"full": full})
    return {"job_id": job_id, "full": full}


@router.get("/index/status")
def index_status(request: Request, token: str = Depends(require_token)):
    return service(request).report.index_status()


@router.post("/github/webhook")
async def github_webhook(request: Request):
    """Receive a GitHub event. Signed by GitHub, so no bearer token."""
    cfg = service(request).config.github
    if not cfg.enabled:
        raise HTTPException(status_code=404, detail="github integration disabled")
    raw = await request.body()
    if cfg.webhook_secret and not verify_signature(
        cfg.webhook_secret, raw, request.headers.get("x-hub-signature-256", "")
    ):
        raise HTTPException(status_code=401, detail="bad signature")
    if not cfg.webhook_secret:
        raise HTTPException(status_code=403, detail="set github.webhook_secret to use webhooks")

    job = job_for(request.headers.get("x-github-event", ""), json.loads(raw), cfg)
    if job is None:
        return {"ok": True, "queued": False}
    kind, payload = job
    return {"ok": True, "queued": True, "job_id": queue(request).enqueue(kind, payload)}


@router.get("/healthz")
def healthz(request: Request):
    return {"ok": True, "schema_version": SCHEMA_VERSION, "pending_jobs": queue(request).pending()}


@router.get("/doctor")
def doctor(request: Request, token: str = Depends(require_token)):
    return service(request).report.doctor()


@router.get("/schema")
def schema(request: Request, token: str = Depends(require_token)):
    prompts = service(request).prompts
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_set": prompts.version(),
        "prompts": prompts.report(),
        "events": [
            "review_started",
            "unit_started",
            "finding",
            "finding_suppressed",
            "unit_complete",
            "review_complete",
            "superseded",
            "error",
        ],
    }


@router.get("/guide", response_class=PlainTextResponse)
def guide(request: Request, topic: str | None = None):
    return guide_text(topic, service(request).config.github.mention)
