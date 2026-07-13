from __future__ import annotations

import hashlib
import json
from time import monotonic
from typing import Any

from backend.common import LLMError
from backend.common.logging import get_logger
from backend.common.metrics import incr, record_latency_sample_nowait
from backend.common.prometheus_metrics import observe_llm_request
from backend.common.types import LLMRequest, LLMResponse, LLMUsage


def adapter_logger(component: str) -> Any:
    return get_logger(component=component)


def log_llm_request_start(
    logger: Any,
    *,
    model: str,
    provider: str,
    request_type: str,
) -> float:
    started_at = monotonic()
    logger.info(
        "llm_request_start",
        model=model,
        provider=provider,
        request_type=request_type,
    )
    return started_at


def log_llm_request_end(
    logger: Any,
    *,
    model: str,
    provider: str,
    request_type: str,
    started_at: float,
    response: LLMResponse | None = None,
) -> None:
    duration_seconds = monotonic() - started_at
    duration_ms = int(duration_seconds * 1000)
    payload: dict[str, Any] = {
        "model": model,
        "provider": provider,
        "request_type": request_type,
        "duration_ms": duration_ms,
    }
    tokens: dict[str, int] = {}
    if response is not None:
        payload["prompt_tokens"] = response.usage.prompt_tokens
        payload["completion_tokens"] = response.usage.completion_tokens
        payload["cached_prompt_tokens"] = response.usage.cached_prompt_tokens
        payload["cache_creation_prompt_tokens"] = response.usage.cache_creation_prompt_tokens
        tokens = {
            "prompt": response.usage.prompt_tokens,
            "completion": response.usage.completion_tokens,
            "cached_prompt": response.usage.cached_prompt_tokens,
            "cache_creation_prompt": response.usage.cache_creation_prompt_tokens,
        }
    observe_llm_request(provider, model, request_type, "success", duration_seconds, tokens=tokens)
    record_latency_sample_nowait("llm_request", duration_ms)
    logger.info("llm_request_end", **payload)


def log_prefix_fingerprint(logger: Any, request: LLMRequest, payload: dict[str, Any]) -> None:
    """记录实发前缀(system+tools)与 messages 指纹，用于跨请求比对 prompt cache 前缀是否字节稳定。"""
    tools = payload.get("tools") or []
    names = [str(tool.get("name", "")) for tool in tools]
    prefix_bytes = json.dumps(
        {"system": payload.get("system"), "tools": tools},
        ensure_ascii=False,
    ).encode("utf-8")
    messages = payload.get("messages") or []
    messages_bytes = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    logger.info(
        "llm_prefix_fingerprint",
        cache_prefix_hash=(request.cache_prefix_hash or "")[:16],
        payload_prefix_sha=hashlib.sha256(prefix_bytes).hexdigest()[:16],
        tools_count=str(len(names)),
        tools_names="|".join(names),
        messages_sha=hashlib.sha256(messages_bytes).hexdigest()[:16],
        messages_count=str(len(messages)),
        messages_bytes=str(len(messages_bytes)),
    )


def log_llm_request_retry(
    logger: Any,
    *,
    attempt: int,
    provider: str,
    request_type: str,
    reason: str,
    status_code: int | None = None,
) -> None:
    logger.warning(
        "llm_request_retry",
        provider=provider,
        request_type=request_type,
        attempt=attempt,
        status_code=status_code,
        reason=reason,
    )


def log_llm_request_error(
    logger: Any,
    *,
    model: str,
    provider: str,
    request_type: str,
    exc: Exception,
    started_at: float | None = None,
) -> None:
    if started_at is not None:
        duration_seconds = monotonic() - started_at
        observe_llm_request(
            provider,
            model,
            request_type,
            "error",
            duration_seconds,
            error_code=exc.code if isinstance(exc, LLMError) else type(exc).__name__,
        )
        record_latency_sample_nowait("llm_request", int(duration_seconds * 1000))
    logger.error(
        "llm_request_error",
        model=model,
        provider=provider,
        request_type=request_type,
        error_code=exc.code if isinstance(exc, LLMError) else type(exc).__name__,
        error_message=str(exc),
    )


async def incr_llm_success(response: LLMResponse | None = None) -> None:
    await incr_llm_success_usage(response.usage if response else None)


async def incr_llm_success_usage(usage: LLMUsage | None) -> None:
    await incr("llm_calls")
    if usage is None:
        return
    await incr("llm_prompt_tokens", usage.prompt_tokens)
    await incr("llm_completion_tokens", usage.completion_tokens)
    if usage.cached_prompt_tokens:
        await incr("llm_cached_prompt_tokens", usage.cached_prompt_tokens)
    if usage.cache_creation_prompt_tokens:
        await incr("llm_cache_creation_tokens", usage.cache_creation_prompt_tokens)


async def incr_llm_error() -> None:
    await incr("llm_errors")


__all__ = [
    "adapter_logger",
    "incr_llm_error",
    "incr_llm_success",
    "incr_llm_success_usage",
    "log_llm_request_end",
    "log_llm_request_error",
    "log_llm_request_retry",
    "log_llm_request_start",
    "log_prefix_fingerprint",
]
