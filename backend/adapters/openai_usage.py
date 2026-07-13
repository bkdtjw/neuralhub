from __future__ import annotations

from typing import Any

from backend.common.types import StreamChunk


def usage_stream_chunk(data: dict[str, Any]) -> StreamChunk | None:
    """Build a usage StreamChunk from an OpenAI SSE frame, if it carries usage.

    OpenAI-compatible providers emit token totals on a trailing SSE frame whose
    ``choices`` is empty and whose ``usage`` holds the counts (only when the
    request asked for ``stream_options.include_usage`` -- or when the gateway
    volunteers it). Frames without usage return ``None`` and leave the stream
    unchanged, so providers that never send it stay usage-free rather than 400.
    """
    usage = data.get("usage")
    if not isinstance(usage, dict) or not usage:
        return None
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    cached_int = int(cached or 0)
    # 统一"未命中输入"口径：OpenAI 的 prompt_tokens 含 cached_tokens，而
    # Anthropic 的 input_tokens 不含——此处扣除，命中率分母才不重复计缓存部分。
    return StreamChunk(
        type="usage",
        data={
            "prompt_tokens": max(int(usage.get("prompt_tokens", 0) or 0) - cached_int, 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "cached_prompt_tokens": cached_int,
        },
    )


__all__ = ["usage_stream_chunk"]
