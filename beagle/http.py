from __future__ import annotations

import random
import time

import httpx

RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_BACKOFF_SECONDS = 30.0


def backoff(attempt: int, response: httpx.Response | None = None) -> None:
    """Wait before trying again, for as long as the service asks or longer."""
    retry_after = response.headers.get("retry-after") if response is not None else None
    if retry_after and retry_after.isdigit():
        time.sleep(min(float(retry_after), MAX_BACKOFF_SECONDS))
        return
    time.sleep(min(2**attempt + random.random(), MAX_BACKOFF_SECONDS))
