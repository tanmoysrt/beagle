"""Time helpers shared across the service.

ISO-8601 UTC strings for human-facing record timestamps; integer epoch seconds
for JWT ``iat`` / ``exp`` claims.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat()


def epoch_seconds() -> int:
    return int(now().timestamp())
