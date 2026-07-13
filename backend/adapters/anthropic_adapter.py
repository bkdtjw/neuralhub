from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json

import httpx

from backend.adapters.base import LLMAdapter
from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, LLMUsage, Message, ProviderConfig, StreamChunk
from backend.config.http_client import load_http_client_config

from .anthropic_stream import fold_usage, new_usage_acc, stream_usage_response
from .anthropic_support import (
    build_headers,
    build_payload,
    parse_response,
    parse_stream_line,
    to_anthropic_messages,
)
from .http_error_support import error_message, is_context_overflow
from .logging_support import (
    adapter_logger,
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_retry,
    log_llm_request_start,
    log_prefix_fingerprint,
)


def _capture_anthropic_usage(raw: str, holder: dict[str, int]) -> None:
    try:
        data = json.loads(raw)
    except ValueError:
        return
    usage = data.get("usage") or (data.get("message") or {}).get("usage")
    if not isinstance(usage, dict):
        return
    if isinstance(usage.get("input_tokens"), int):
        holder["prompt"] = usage["input_tokens"]
    if isinstance(usage.get("output_tokens"), int):
        holder["completion"] = usage["output_tokens"]
    cached = usage.get("cache_read_input_tokens")
    if isinstance(cached, int) and cached > 0:
        holder["cached"] = cached


def _stream_usage(holder: dict[str, int]) -> LLMUsage | None:
    if not holder:
        return None
    return LLMUsage(
        prompt_tokens=holder.get("prompt", 0),
        completion_tokens=holder.get("completion", 0),
        cached_prompt_tokens=holder.get("cached", 0),
    )

logger = adapter_logger("anthropic_adapter")
_REQUEST_TIMEOUT_SECONDS = 120.0


class AnthropicAdapter(LLMAdapter):
    def __init__(self, config: ProviderConfig) -> None:
        base_url = config.base_url.rstrip("/") if config.base_url else "https://api.anthropic.com/v1"
        self._api_key = config.api_key
        self._url = self._messages_url(base_url)
        self._provider = config.provider_type.value
        self._default_model = config.default_model
        self._extra_headers = dict(config.extra_headers)
        self._max_retries = 3

    async def test_connection(self) -> bool:
        success = False
        try:
            payload = {
                "model": self._default_model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
            }
            async with httpx.AsyncClient(timeout=15.0, trust_env=load_http_client_config().trust_env) as client:
                response = await client.post(self._url, headers=self._headers(), json=payload)
            self._raise_for_status(response)
            success = response.is_success
            return success
        except Exception:
            return False
        finally:
            logger.info("provider_test", provider=self._provider, success=success)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model
        payload = build_payload(request, self._default_model, stream=False)
        log_prefix_fingerprint(logger, request, payload)
        started_at = log_llm_request_start(logger, model=model, provider=self._provider, request_type="complete")
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, trust_env=load_http_client_config().trust_env) as client:
                    response = await client.post(self._url, headers=self._headers(), json=payload)
                if self._is_retryable_status(response.status_code) and attempt < self._max_retries:
                    log_llm_request_retry(
                        logger,
                        attempt=attempt,
                        provider=self._provider,
                        request_type="complete",
                        reason=f"HTTP {response.status_code}",
                        status_code=response.status_code,
                    )
                    await self._backoff(attempt, f"HTTP {response.status_code}")
                    continue
                self._raise_for_status(response)
                result = parse_response(response.json())
                await incr_llm_success(result)
                log_llm_request_end(logger, model=model, provider=self._provider, request_type="complete", started_at=started_at, response=result)
                return result
            except LLMError as exc:
                await incr_llm_error()
                log_llm_request_error(logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at)
                raise
            except httpx.RequestError as exc:
                if self._is_retryable_request_error(exc) and attempt < self._max_retries:
                    log_llm_request_retry(logger, attempt=attempt, provider=self._provider, request_type="complete", reason=type(exc).__name__)
                    await self._backoff(attempt, type(exc).__name__)
                    continue
                await incr_llm_error()
                log_llm_request_error(logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at)
                raise LLMError("NETWORK_ERROR", str(exc), self._provider, None) from exc
            except Exception as exc:
                await incr_llm_error()
                log_llm_request_error(logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at)
                raise LLMError("COMPLETE_ERROR", str(exc), self._provider, None) from exc
        raise LLMError("COMPLETE_ERROR", "Completion failed without response", self._provider, None)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        model = request.model or self._default_model
        payload = build_payload(request, self._default_model, stream=True)
        log_prefix_fingerprint(logger, request, payload)
        tool_blocks: dict[int, dict[str, object]] = {}
        thinking_blocks: dict[int, dict[str, object]] = {}
        usage_acc = new_usage_acc()
        started_at = log_llm_request_start(logger, model=model, provider=self._provider, request_type="stream")
        try:
            for attempt in range(1, self._max_retries + 1):
                async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, trust_env=load_http_client_config().trust_env) as client:
                    async with client.stream("POST", self._url, headers=self._headers(), json=payload) as response:
                        if response.status_code == 429 and attempt < self._max_retries:
                            log_llm_request_retry(logger, attempt=attempt, provider=self._provider, request_type="stream", reason="HTTP 429", status_code=429)
                            await asyncio.sleep(float(attempt))
                            continue
                        if response.status_code >= 400:
                            await response.aread()
                        self._raise_for_status(response)
                        event_type = ""
                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                event_type = line.split(":", 1)[1].strip()
                                continue
                            if not line.startswith("data:"):
                                continue
                            raw = line.split(":", 1)[1].strip()
                            chunk = parse_stream_line(
                                event_type,
                                raw,
                                self._provider,
                                tool_blocks,
                                thinking_blocks,
                            )
                            if chunk is None:
                                continue
                            yield chunk
                            if chunk.type == "usage":
                                fold_usage(usage_acc, chunk)
                                continue
                            if chunk.type == "done":
                                response = stream_usage_response(usage_acc)
                                await incr_llm_success(response)
                                log_llm_request_end(logger, model=model, provider=self._provider, request_type="stream", started_at=started_at, response=response)
                                return
                        response = stream_usage_response(usage_acc)
                        await incr_llm_success(response)
                        log_llm_request_end(logger, model=model, provider=self._provider, request_type="stream", started_at=started_at, response=response)
                        yield StreamChunk(type="done")
                        return
            raise LLMError("RATE_LIMIT", "Anthropic rate limited", self._provider, 429)
        except LLMError as exc:
            await incr_llm_error()
            log_llm_request_error(logger, model=model, provider=self._provider, request_type="stream", exc=exc, started_at=started_at)
            raise
        except httpx.RequestError as exc:
            await incr_llm_error()
            log_llm_request_error(logger, model=model, provider=self._provider, request_type="stream", exc=exc, started_at=started_at)
            raise LLMError("NETWORK_ERROR", str(exc), self._provider, None) from exc
        except Exception as exc:
            await incr_llm_error()
            log_llm_request_error(logger, model=model, provider=self._provider, request_type="stream", exc=exc, started_at=started_at)
            raise LLMError("STREAM_ERROR", str(exc), self._provider, None) from exc

    def _headers(self) -> dict[str, str]:
        return build_headers(self._api_key, self._extra_headers)

    @staticmethod
    def _messages_url(base_url: str) -> str:
        if base_url.endswith("/messages"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/messages"
        return f"{base_url}/v1/messages"

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict[str, object]]:
        return to_anthropic_messages(messages)

    def _parse_response(self, data: dict[str, object]) -> LLMResponse:
        return parse_response(data)  # type: ignore[arg-type]

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise LLMError("RATE_LIMIT", "Anthropic rate limited", self._provider, 429)
        if response.status_code == 401:
            raise LLMError("AUTH_ERROR", "Invalid Anthropic API key", self._provider, 401)
        if 500 <= response.status_code < 600:
            raise LLMError("SERVER_ERROR", "Anthropic server error", self._provider, response.status_code)
        if response.status_code >= 400:
            message = error_message(response)
            code = "CONTEXT_OVERFLOW" if is_context_overflow(message) else "API_ERROR"
            raise LLMError(code, message, self._provider, response.status_code)
