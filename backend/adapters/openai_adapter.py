from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from backend.adapters.base import LLMAdapter
from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, Message, ProviderConfig, StreamChunk
from backend.config.http_client import load_http_client_config

from .http_error_support import error_message, is_context_overflow
from .logging_support import (
    adapter_logger,
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_retry,
    log_llm_request_start,
)
from .openai_streaming import stream_response
from .openai_support import (
    build_headers,
    build_payload,
    parse_response,
    to_openai_messages,
)

logger = adapter_logger("openai_adapter")


class OpenAICompatAdapter(LLMAdapter):
    """OpenAI-compatible endpoint adapter."""

    def __init__(self, config: ProviderConfig) -> None:
        self._provider = config.provider_type.value
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"
        self._api_key = config.api_key
        self._default_model = config.default_model
        self._extra_headers = dict(config.extra_headers)
        self._extra_body = dict(config.extra_body)
        # Opt-in per provider via extra_body: gateways that reject
        # stream_options simply leave it unset (usage stays 0, no 400).
        self._stream_usage = bool(self._extra_body.pop("stream_usage", False))
        self._enable_prompt_cache = config.enable_prompt_cache
        self._prompt_cache_retention = config.prompt_cache_retention
        self._max_retries = 3
        self._logger = logger

    async def test_connection(self) -> bool:
        success = False
        try:
            payload = {
                "model": self._default_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            async with httpx.AsyncClient(
                timeout=15.0, trust_env=load_http_client_config().trust_env
            ) as client:
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
        payload = self._build_payload(request, stream=False)
        started_at = log_llm_request_start(
            logger, model=model, provider=self._provider, request_type="complete"
        )
        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=120.0, trust_env=load_http_client_config().trust_env
                ) as client:
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
                log_llm_request_error(
                    logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at
                )
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
                log_llm_request_error(
                    logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at
                )
                raise LLMError("NETWORK_ERROR", str(exc), self._provider, None) from exc
            except Exception as exc:
                await incr_llm_error()
                log_llm_request_error(
                    logger, model=model, provider=self._provider, request_type="complete", exc=exc, started_at=started_at
                )
                raise LLMError("COMPLETE_ERROR", str(exc), self._provider, None) from exc
        raise LLMError("COMPLETE_ERROR", "Completion failed without response", self._provider, None)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        async for chunk in stream_response(self, request):
            yield chunk

    def _headers(self) -> dict[str, str]:
        return build_headers(self._api_key, self._extra_headers)

    def _build_payload(self, request: LLMRequest, *, stream: bool) -> dict[str, object]:
        return build_payload(
            request,
            self._default_model,
            stream=stream,
            extra_body=self._extra_body,
            enable_prompt_cache=self._enable_prompt_cache,
            prompt_cache_retention=self._prompt_cache_retention,
            include_usage=self._stream_usage,
        )

    def _to_openai_messages(self, messages: list[Message]) -> list[dict[str, object]]:
        return to_openai_messages(messages)

    def _parse_response(self, data: dict[str, object]) -> LLMResponse:
        return parse_response(data)  # type: ignore[arg-type]

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise self._rate_limit_error(response)
        if response.status_code == 401:
            raise LLMError("AUTH_ERROR", "Invalid API key", self._provider, 401)
        if 500 <= response.status_code < 600:
            raise LLMError(
                "SERVER_ERROR", "Provider server error", self._provider, response.status_code
            )
        if response.status_code >= 400:
            message = error_message(response)
            code = "CONTEXT_OVERFLOW" if is_context_overflow(message) else "API_ERROR"
            raise LLMError(code, message, self._provider, response.status_code)

    def _rate_limit_error(self, response: httpx.Response) -> LLMError:
        code = "RATE_LIMIT"
        message = "Provider rate limited"
        try:
            data = response.json()
            if isinstance(data, dict):
                detail = data.get("error")
                if isinstance(detail, dict):
                    provider_code = detail.get("code")
                    provider_message = detail.get("message")
                else:
                    provider_code = data.get("code")
                    provider_message = data.get("message") or data.get("msg")
                if provider_code:
                    code = f"RATE_LIMIT_{provider_code}"
                if provider_message:
                    message = str(provider_message)
        except Exception:
            pass
        return LLMError(code, message, self._provider, 429)
