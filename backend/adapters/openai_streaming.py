from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json
from typing import Any

import httpx

from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, LLMUsage, StreamChunk
from backend.config.http_client import load_http_client_config

from .logging_support import (
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_retry,
    log_llm_request_start,
)
from .openai_support import flush_tool_calls, parse_stream_line


@dataclass(frozen=True)
class StreamState:
    adapter: Any
    payload: dict[str, Any]
    model: str
    started_at: float
    usage: dict[str, int] = field(default_factory=dict)


def capture_stream_usage(raw: str, holder: dict[str, int]) -> None:
    try:
        usage = json.loads(raw).get("usage")
    except ValueError:
        return
    if not isinstance(usage, dict):
        return
    for source, target in (("prompt_tokens", "prompt"), ("completion_tokens", "completion")):
        value = usage.get(source)
        if isinstance(value, (int, float)) and value >= 0:
            holder[target] = int(value)
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if cached is None:
        cached = usage.get("cached_tokens")
    if isinstance(cached, (int, float)) and cached > 0:
        holder["cached"] = int(cached)


async def stream_response(adapter: Any, request: LLMRequest) -> AsyncIterator[StreamChunk]:
    model = request.model or adapter._default_model  # noqa: SLF001
    payload = adapter._build_payload(request, stream=True)  # noqa: SLF001
    # 让兼容端在最后一个 chunk 返回 usage，token 用量才有来源
    payload.setdefault("stream_options", {"include_usage": True})
    started_at = log_llm_request_start(
        adapter._logger,  # noqa: SLF001
        model=model,
        provider=adapter._provider,  # noqa: SLF001
        request_type="stream",
    )
    state = StreamState(adapter=adapter, payload=payload, model=model, started_at=started_at)
    try:
        async for chunk in _stream_attempts(state):
            yield chunk
    except LLMError as exc:
        await _log_stream_error(adapter, model, exc, started_at)
        raise
    except httpx.RequestError as exc:
        await _log_stream_error(adapter, model, exc, started_at)
        raise LLMError("NETWORK_ERROR", str(exc), adapter._provider, None) from exc  # noqa: SLF001
    except Exception as exc:
        await _log_stream_error(adapter, model, exc, started_at)
        raise LLMError("STREAM_ERROR", str(exc), adapter._provider, None) from exc  # noqa: SLF001


async def _stream_attempts(state: StreamState) -> AsyncIterator[StreamChunk]:
    adapter = state.adapter
    for attempt in range(1, adapter._max_retries + 1):  # noqa: SLF001
        async with httpx.AsyncClient(
            timeout=120.0,
            trust_env=load_http_client_config().trust_env,
        ) as client:
            async with client.stream(
                "POST",
                adapter._url,  # noqa: SLF001
                headers=adapter._headers(),  # noqa: SLF001
                json=state.payload,
            ) as response:
                if response.status_code == 429 and attempt < adapter._max_retries:  # noqa: SLF001
                    log_llm_request_retry(
                        adapter._logger,  # noqa: SLF001
                        attempt=attempt,
                        provider=adapter._provider,  # noqa: SLF001
                        request_type="stream",
                        reason="HTTP 429",
                        status_code=429,
                    )
                    await adapter._backoff(attempt, "HTTP 429")  # noqa: SLF001
                    continue
                async for chunk in _handle_stream_response(state, response):
                    yield chunk
                return
    raise LLMError("RATE_LIMIT", "Provider rate limited", adapter._provider, 429)  # noqa: SLF001


async def _handle_stream_response(
    state: StreamState,
    response: httpx.Response,
) -> AsyncIterator[StreamChunk]:
    adapter = state.adapter
    if response.status_code >= 400:
        await response.aread()
    adapter._raise_for_status(response)  # noqa: SLF001
    tool_chunks: dict[int, dict[str, str]] = {}
    usage: dict[str, int] | None = None
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw == "[DONE]":
            for chunk in flush_tool_calls(tool_chunks):
                yield chunk
            await _finish_stream(state, usage)
            yield StreamChunk(type="done")
            return
        if '"usage"' in raw:
            capture_stream_usage(raw, state.usage)
        for chunk in parse_stream_line(raw, tool_chunks):
            if chunk.type == "usage" and isinstance(chunk.data, dict):
                usage = chunk.data
            yield chunk
    for chunk in flush_tool_calls(tool_chunks):
        yield chunk
    await _finish_stream(state, usage)
    yield StreamChunk(type="done")


async def _finish_stream(state: StreamState, usage: dict[str, int] | None = None) -> None:
    adapter = state.adapter
    response = LLMResponse(content="", usage=LLMUsage(**usage)) if usage else None
    await incr_llm_success(response)
    log_llm_request_end(
        adapter._logger,  # noqa: SLF001
        model=state.model,
        provider=adapter._provider,  # noqa: SLF001
        request_type="stream",
        started_at=state.started_at,
        response=response,
    )


async def _log_stream_error(adapter: Any, model: str, exc: Exception, started_at: float) -> None:
    await incr_llm_error()
    log_llm_request_error(
        adapter._logger,  # noqa: SLF001
        model=model,
        provider=adapter._provider,  # noqa: SLF001
        request_type="stream",
        exc=exc,
        started_at=started_at,
    )


__all__ = ["capture_stream_usage", "stream_response"]
