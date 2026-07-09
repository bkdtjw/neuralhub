from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, LLMUsage, ProviderConfig, StreamChunk, ToolCall
from backend.config.http_client import load_http_client_config

from .logging_support import (
    adapter_logger,
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_retry,
    log_llm_request_start,
)
from .openai_adapter import OpenAICompatAdapter

logger = adapter_logger("ollama_adapter")


class OllamaAdapter(OpenAICompatAdapter):
    """Local Ollama adapter."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        base = (config.base_url or "http://localhost:11434").rstrip("/")
        root = base[:-9] if base.endswith("/api/chat") else base[:-4] if base.endswith("/api") else base
        self._url = base if base.endswith("/api/chat") else (f"{base}/chat" if base.endswith("/api") else f"{base}/api/chat")
        self._tags_url = f"{root}/api/tags"
        self._api_key = ""
        self._provider = "ollama"

    async def test_connection(self) -> bool:
        success = False
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=load_http_client_config().trust_env) as client:
                response = await client.get(self._tags_url, headers=self._headers())
            success = response.is_success
            return success
        except Exception:
            return False
        finally:
            logger.info("provider_test", provider=self._provider, success=success)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model
        payload = self._build_payload(request, stream=False)
        started_at = log_llm_request_start(logger, model=model, provider=self._provider, request_type="complete")
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0, trust_env=load_http_client_config().trust_env) as client:
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
                result = self._parse_response(response.json())
                await incr_llm_success(result)
                log_llm_request_end(
                    logger,
                    model=model,
                    provider=self._provider,
                    request_type="complete",
                    started_at=started_at,
                    response=result,
                )
                return result
            except LLMError as exc:
                await incr_llm_error()
                log_llm_request_error(logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at)
                raise
            except httpx.RequestError as exc:
                if self._is_retryable_request_error(exc) and attempt < self._max_retries:
                    log_llm_request_retry(
                        logger,
                        attempt=attempt,
                        provider=self._provider,
                        request_type="complete",
                        reason=type(exc).__name__,
                    )
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
        payload = self._build_payload(request, stream=True)
        started_at = log_llm_request_start(logger, model=model, provider=self._provider, request_type="stream")
        try:
            async with httpx.AsyncClient(timeout=60.0, trust_env=load_http_client_config().trust_env) as client:
                async with client.stream("POST", self._url, headers=self._headers(), json=payload) as response:
                    if response.status_code >= 400:
                        await response.aread()
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        raw = line.split(":", 1)[1].strip() if line.startswith("data:") else line.strip()
                        if not raw:
                            continue
                        data = json.loads(raw)
                        message = data.get("message", {})
                        if message.get("reasoning_content"):
                            yield StreamChunk(type="reasoning", data=message["reasoning_content"])
                        if message.get("content"):
                            yield StreamChunk(type="text", data=message["content"])
                        for tool_call in message.get("tool_calls", []) or []:
                            function = tool_call.get("function", {})
                            yield StreamChunk(type="tool_call", data={"id": tool_call.get("id", ""), "name": function.get("name", ""), "arguments": function.get("arguments", {})})
                        if data.get("done"):
                            usage = LLMUsage(prompt_tokens=data.get("prompt_eval_count", 0), completion_tokens=data.get("eval_count", 0))
                            yield StreamChunk(type="usage", data={"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "cached_prompt_tokens": 0})
                            result = LLMResponse(content="", usage=usage)
                            await incr_llm_success(result)
                            log_llm_request_end(
                                logger,
                                model=model,
                                provider=self._provider,
                                request_type="stream",
                                started_at=started_at,
                                response=result,
                            )
                            yield StreamChunk(type="done")
                            return
                    await incr_llm_success()
                    log_llm_request_end(
                        logger,
                        model=model,
                        provider=self._provider,
                        request_type="stream",
                        started_at=started_at,
                    )
                    yield StreamChunk(type="done")
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

    def _build_payload(self, request: LLMRequest, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": self._to_openai_messages(request.messages),
            "stream": stream,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.tools:
            payload["tools"] = self._to_openai_tools(request.tools)
        return payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        message = data.get("message", {})
        tool_calls = [ToolCall(id=tool_call.get("id", ""), name=tool_call.get("function", {}).get("name", ""), arguments=tool_call.get("function", {}).get("arguments", {}) or {}) for tool_call in message.get("tool_calls", []) or []]
        provider_metadata = {"reasoning_content": message["reasoning_content"]} if isinstance(message.get("reasoning_content"), str) and message.get("reasoning_content") else {}
        return LLMResponse(
            content=message.get("content", "") or "",
            tool_calls=tool_calls,
            usage=LLMUsage(prompt_tokens=data.get("prompt_eval_count", 0), completion_tokens=data.get("eval_count", 0)),
            provider_metadata=provider_metadata,
        )

    def _headers(self) -> dict[str, str]:
        return {"content-type": "application/json", **self._extra_headers}
