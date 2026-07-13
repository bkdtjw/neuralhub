from __future__ import annotations

import json

import pytest

from backend.adapters import logging_support
from backend.adapters.anthropic_adapter import _capture_anthropic_usage
from backend.adapters.openai_streaming import capture_stream_usage
from backend.common.types import LLMUsage


def test_capture_stream_usage_openai_final_chunk() -> None:
    holder: dict[str, int] = {}
    raw = json.dumps({
        "choices": [],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "prompt_tokens_details": {"cached_tokens": 30},
        },
    })
    capture_stream_usage(raw, holder)
    # 未命中输入口径：prompt 已扣除 cached（120-30=90）。
    assert holder == {"prompt": 90, "completion": 45, "cached": 30}


def test_capture_stream_usage_kimi_style_cached_tokens() -> None:
    holder: dict[str, int] = {}
    raw = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 6}})
    capture_stream_usage(raw, holder)
    assert holder == {"prompt": 4, "completion": 2, "cached": 6}


def test_capture_stream_usage_ignores_invalid_payload() -> None:
    holder: dict[str, int] = {}
    capture_stream_usage("not-json", holder)
    capture_stream_usage(json.dumps({"usage": "oops"}), holder)
    assert holder == {}


def test_capture_anthropic_usage_from_start_and_delta() -> None:
    holder: dict[str, int] = {}
    start = json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 88, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 25}}})
    delta = json.dumps({"type": "message_delta", "usage": {"output_tokens": 17}})
    _capture_anthropic_usage(start, holder)
    _capture_anthropic_usage(delta, holder)
    assert holder == {"prompt": 88, "cached": 40, "cache_creation": 25, "completion": 17}


@pytest.mark.asyncio
async def test_incr_llm_success_usage_records_token_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_incr(metric: str, value: int = 1) -> None:
        calls.append((metric, value))

    monkeypatch.setattr(logging_support, "incr", fake_incr)
    await logging_support.incr_llm_success_usage(
        LLMUsage(prompt_tokens=100, completion_tokens=20, cached_prompt_tokens=5, cache_creation_prompt_tokens=7)
    )
    assert ("llm_calls", 1) in calls
    assert ("llm_prompt_tokens", 100) in calls
    assert ("llm_completion_tokens", 20) in calls
    assert ("llm_cached_prompt_tokens", 5) in calls
    assert ("llm_cache_creation_tokens", 7) in calls


@pytest.mark.asyncio
async def test_incr_llm_success_usage_without_usage_only_counts_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_incr(metric: str, value: int = 1) -> None:
        calls.append((metric, value))

    monkeypatch.setattr(logging_support, "incr", fake_incr)
    await logging_support.incr_llm_success_usage(None)
    assert calls == [("llm_calls", 1)]
