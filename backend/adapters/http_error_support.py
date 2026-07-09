from __future__ import annotations

import httpx

# Substrings (matched case-insensitively) that mark a context-length /
# prompt-too-long 4xx from any supported provider. Kept module-level so the
# OpenAI and Anthropic adapters classify overflow identically; extend this
# tuple when a new provider surfaces a distinct overflow phrase.
CONTEXT_OVERFLOW_MARKERS: tuple[str, ...] = (
    "prompt is too long",
    "context_length_exceeded",
    "maximum context length",
    "input length and max_tokens exceed",
)


def error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("message", response.text)
    except Exception:
        try:
            return response.text
        except Exception:
            return f"HTTP {response.status_code}"


def is_context_overflow(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in CONTEXT_OVERFLOW_MARKERS)


__all__ = ["error_message", "is_context_overflow", "CONTEXT_OVERFLOW_MARKERS"]
