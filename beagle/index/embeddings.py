from __future__ import annotations

import hashlib
import time

import httpx

from ..config import EmbeddingsCfg
from ..errors import ProviderError
from ..http import RETRY_STATUSES, backoff
from ..storage.dao import CallLog

MAX_ATTEMPTS = 5
# A refused connection is not a busy server: fail fast instead of backing off.
TRANSPORT_ATTEMPTS = 2


class EmbeddingClient:
    """Talks to any OpenAI-compatible /embeddings endpoint.

    That one format covers OpenAI, gateways and self-hosted servers, so a local
    model is just a different base_url.
    """

    def __init__(self, cfg: EmbeddingsCfg, call_log: CallLog | None = None, timeout: float = 60.0):
        self.cfg = cfg
        self.call_log = call_log
        self.url = f"{cfg.base_url.rstrip('/')}/embeddings"
        self.send_dimensions = True
        self.client = httpx.Client(timeout=timeout, headers=self.headers())

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        headers.update(self.cfg.headers)
        return headers

    def probe(self) -> int:
        """Check the endpoint answers and returns the width the config promises."""
        vectors = self.embed(["beagle embedding probe"])
        width = len(vectors[0])
        if width != self.cfg.dims:
            raise ProviderError(
                f"embeddings model {self.cfg.model} returned {width} dimensions "
                f"but config says dims = {self.cfg.dims}"
            )
        return width

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.cfg.model, "input": texts}
        if self.send_dimensions:
            payload["dimensions"] = self.cfg.dims
        data = self.post_with_retries(payload)
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]
        if any(len(vector) != self.cfg.dims for vector in vectors):
            raise ProviderError(
                f"embeddings endpoint returned {len(vectors[0])} dimensions, expected {self.cfg.dims}"
            )
        return vectors

    def post_with_retries(self, payload: dict) -> dict:
        started = time.monotonic()
        last_error = None
        transport_failures = 0
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.client.post(self.url, json=payload)
            except httpx.HTTPError as exc:
                last_error = ProviderError(f"embeddings request failed: {exc}", retryable=True)
                transport_failures += 1
                if transport_failures >= TRANSPORT_ATTEMPTS:
                    break
                time.sleep(0.5)
                continue

            if response.status_code == 200:
                data = response.json()
                self.log_call(payload, data, started)
                return data
            if self.should_drop_dimensions(response, payload):
                payload.pop("dimensions")
                self.send_dimensions = False
                continue
            last_error = self.error_for(response)
            if response.status_code not in RETRY_STATUSES:
                break
            backoff(attempt, response)

        self.log_call(payload, None, started, error=str(last_error))
        raise last_error or ProviderError("embeddings request failed")

    def should_drop_dimensions(self, response: httpx.Response, payload: dict) -> bool:
        """Some models and self-hosted servers reject the dimensions parameter."""
        return (
            response.status_code == 400
            and "dimensions" in payload
            and "dimension" in response.text.lower()
        )

    def error_for(self, response: httpx.Response) -> ProviderError:
        detail = response.text[:300].replace("\n", " ")
        return ProviderError(
            f"embeddings endpoint returned {response.status_code}: {detail}",
            status=response.status_code,
            retryable=response.status_code in RETRY_STATUSES,
        )

    def log_call(
        self, payload: dict, data: dict | None, started: float, error: str | None = None
    ) -> None:
        if self.call_log is None:
            return
        usage = (data or {}).get("usage", {})
        inputs = payload.get("input", [])
        self.call_log.record(
            request_hash=hash_payload(payload),
            model=self.cfg.model,
            request={"model": self.cfg.model, "batch": len(inputs), "dims": self.cfg.dims},
            response={"usage": usage} if data else None,
            prompt_name="embeddings",
            tokens_in=usage.get("prompt_tokens", 0) or usage.get("total_tokens", 0),
            latency_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )

    def close(self) -> None:
        self.client.close()


def hash_payload(payload: dict) -> str:
    inputs = payload.get("input", [])
    joined = "\n".join(inputs) if isinstance(inputs, list) else str(inputs)
    return hashlib.sha256(f"{payload.get('model')}:{joined}".encode()).hexdigest()
