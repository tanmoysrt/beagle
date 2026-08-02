from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..errors import ProviderError
from ..http import RETRY_STATUSES, backoff

log = logging.getLogger("beagle.llm.openai")

STOP_REASONS = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}


@dataclass
class Block:
    type: str
    text: str = ""
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Message:
    """An OpenAI answer wearing the shape the rest of Beagle already reads."""

    content: list[Block]
    usage: Usage
    model: str
    stop_reason: str | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "content": [block.model_dump() for block in self.content],
            "model": self.model,
            "stop_reason": self.stop_reason,
            "usage": self.usage.__dict__,
        }


class OpenAIMessages:
    """Talks to an OpenAI-compatible service, and answers like the Anthropic one.

    A gateway that serves several vendors often translates everything except
    tools, so the request is built in the OpenAI shape here rather than sent in
    the Anthropic shape and hoped for.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        headers: dict[str, str],
        timeout: float,
        max_retries: int = 3,
    ):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.max_retries = max_retries
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", **headers},
            transport=httpx.HTTPTransport(retries=max_retries),
        )

    def create(self, **request: Any) -> Message:
        """A gateway that answers 500 once will often answer the same call.

        One lost turn costs a whole unit of review, because the conversation
        cannot go on without it, so a passing fault is worth waiting out.
        """
        body = to_openai(request)
        for attempt in range(self.max_retries + 1):
            response = self.client.post(self.url, json=body)
            if response.status_code == 200:
                return from_openai(response.json(), request["model"])
            if response.status_code not in RETRY_STATUSES or attempt == self.max_retries:
                raise ProviderError(
                    f"llm request failed ({response.status_code}): {response.text[:300]}",
                    status=response.status_code,
                    retryable=response.status_code in RETRY_STATUSES,
                )
            log.info("retrying after %s from the model service", response.status_code)
            backoff(attempt, response)
        raise ProviderError("llm request failed after every retry")


def to_openai(request: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request["model"],
        "max_tokens": request.get("max_tokens", 4096),
        "messages": openai_messages(request),
    }
    if request.get("tools"):
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            }
            for tool in request["tools"]
        ]
    choice = request.get("tool_choice") or {}
    if choice.get("name"):
        body["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    body.update(request.get("extra_body") or {})
    return body


def openai_messages(request: dict[str, Any]) -> list[dict[str, Any]]:
    messages = []
    system = join_text(request.get("system") or [])
    if system:
        messages.append({"role": "system", "content": system})
    for message in request["messages"]:
        messages.extend(convert(message))
    return messages


def convert(message: dict[str, Any]) -> list[dict[str, Any]]:
    role, content = message["role"], message["content"]
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    # A tool answer is its own message, and anything said beside it follows.
    out: list[dict[str, Any]] = [
        {"role": "tool", "tool_call_id": block["tool_use_id"], "content": str(block["content"])}
        for block in content
        if block.get("type") == "tool_result"
    ]
    calls = [
        {
            "id": block["id"],
            "type": "function",
            "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
        }
        for block in content
        if block.get("type") == "tool_use"
    ]
    said = join_text(content)
    if calls:
        out.append({"role": "assistant", "content": said, "tool_calls": calls})
    elif said:
        out.append({"role": role, "content": said})
    return out


def from_openai(payload: dict[str, Any], model: str) -> Message:
    choice = (payload.get("choices") or [{}])[0]
    answer = choice.get("message") or {}
    blocks = []
    if answer.get("content"):
        blocks.append(Block("text", text=answer["content"]))
    for call in answer.get("tool_calls") or []:
        function = call.get("function") or {}
        blocks.append(
            Block(
                "tool_use",
                id=call.get("id"),
                name=function.get("name"),
                input=read_arguments(function.get("arguments")),
            )
        )
    return Message(
        content=blocks,
        usage=usage_of(payload.get("usage") or {}),
        model=payload.get("model") or model,
        stop_reason=STOP_REASONS.get(choice.get("finish_reason"), choice.get("finish_reason")),
    )


def usage_of(raw: dict[str, Any]) -> Usage:
    """`prompt_tokens` already counts the cached part, which Beagle counts apart."""
    cached = (raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return Usage(
        input_tokens=max(0, (raw.get("prompt_tokens") or 0) - cached),
        output_tokens=raw.get("completion_tokens") or 0,
        cache_read_input_tokens=cached,
    )


def read_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def join_text(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n\n".join(
        block["text"] for block in blocks if block.get("type") == "text" and block.get("text")
    )
