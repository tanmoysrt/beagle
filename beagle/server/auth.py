from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request


async def require_token(request: Request, authorization: str = Header(default="")) -> str:
    """Bearer check against the per-consumer tokens in config."""
    tokens = request.app.state.service.config.server.auth_tokens
    if not tokens:
        return "anonymous"
    supplied = authorization.removeprefix("Bearer ").strip()
    for token in tokens:
        if secrets.compare_digest(supplied, token):
            return token
    raise HTTPException(status_code=401, detail="invalid or missing bearer token")
