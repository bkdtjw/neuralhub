from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from backend.adapters.anthropic_adapter import AnthropicAdapter
from backend.adapters.anthropic_stream import parse_stream_line as anthropic_parse
from backend.adapters.base import LLMAdapter
from backend.adapters.ollama_adapter import OllamaAdapter
from backend.adapters.openai_adapter import OpenAICompatAdapter
from backend.adapters.openai_support import build_payload as openai_build_payload
from backend.adapters.openai_support import parse_stream_line as openai_parse
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ProviderConfig,
    ProviderType,
    StreamChunk,
    merge_usage,
)
from backend.core.s01_agent_loop.streaming import complete_with_stream


def _request() -> LLMRequest:
    return LLMRequest(model="m", messages=[Message(role="user", content="hi")])


def _config(provider_type: ProviderType, base_url: str, **extra_body: Any) -> ProviderConfig:
    return ProviderConfig(
        id="t",
        name="t",
        provider_type=provider_type,
        base_url=base_url,
        api_key="k",
        default_model="m",
        extra_body=extra_body,
    )


# --- Anthropic parse (pure logic, no HTTP) ----------------------------------


def test_anthropic_message_start_yields_prompt_and_cached_only() -> None:
    raw = json.dumps(
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 120, "cache_read_input_tokens": 40, "output_tokens": 2}},
        }
    )
    chunk = anthropic_parse("message_start", raw, "anthropic")
    assert chunk is not None and chunk.type == "usage"
    # output_tokens on message_start is the seed (~2) value and must be dropped.
    assert chunk.data == {
        "prompt_tokens": 120,
        "completion_tokens": 0,
        "cached_prompt_tokens": 40,
        "cache_creation_prompt_tokens": 0,
    }


def test_anthropic_message_start_carries_cache_creation_tokens() -> None:
    raw = json.dumps(
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 900, "output_tokens": 1}},
        }
    )
    chunk = anthropic_parse("message_start", raw, "anthropic")
    assert chunk is not None and chunk.type == "usage"
    # 首写缓存的成本单独入账，不混进 prompt/cached，命中率分母才完整。
    assert chunk.data == {
        "prompt_tokens": 20,
        "completion_tokens": 0,
        "cached_prompt_tokens": 0,
        "cache_creation_prompt_tokens": 900,
    }


def test_anthropic_message_delta_yields_completion_only() -> None:
    raw = json.dumps({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 256}})
    chunk = anthropic_parse("message_delta", raw, "anthropic")
    assert chunk is not None and chunk.type == "usage"
    assert chunk.data == {
        "prompt_tokens": 0,
        "completion_tokens": 256,
        "cached_prompt_tokens": 0,
        "cache_creation_prompt_tokens": 0,
    }


def test_anthropic_usage_prompt_from_start_completion_from_delta_not_summed() -> None:
    start = anthropic_parse(
        "message_start",
        json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 120, "cache_read_input_tokens": 40, "output_tokens": 2}}}),
        "anthropic",
    )
    delta = anthropic_parse("message_delta", json.dumps({"type": "message_delta", "usage": {"output_tokens": 256}}), "anthropic")
    acc = {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    assert start is not None and delta is not None
    merge_usage(acc, start.data)
    merge_usage(acc, delta.data)
    # prompt/cached come from message_start, completion from message_delta;
    # nothing is summed and the delta's zeroed prompt never clobbers 120.
    assert acc == {"prompt_tokens": 120, "completion_tokens": 256, "cached_prompt_tokens": 40}


def test_anthropic_message_start_without_usage_is_none() -> None:
    assert anthropic_parse("message_start", json.dumps({"type": "message_start", "message": {}}), "anthropic") is None


def test_anthropic_message_delta_carries_kimi_cache_fields() -> None:
    # Kimi 的 anthropic 兼容层：message_start 报未扣缓存全量，真实 input/cache_read 在 message_delta。
    raw = json.dumps(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": 1, "cache_read_input_tokens": 6761, "output_tokens": 20},
        }
    )
    chunk = anthropic_parse("message_delta", raw, "anthropic")
    assert chunk is not None and chunk.type == "usage"
    assert chunk.data == {
        "prompt_tokens": 1,
        "completion_tokens": 20,
        "cached_prompt_tokens": 6761,
        "cache_creation_prompt_tokens": 0,
    }


def test_anthropic_usage_kimi_delta_overrides_start_full_count() -> None:
    start = anthropic_parse(
        "message_start",
        json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 6762, "cache_read_input_tokens": 0, "output_tokens": 0}}}),
        "anthropic",
    )
    delta = anthropic_parse(
        "message_delta",
        json.dumps({"type": "message_delta", "usage": {"input_tokens": 1, "cache_read_input_tokens": 6761, "output_tokens": 20}}),
        "anthropic",
    )
    acc = {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    assert start is not None and delta is not None
    merge_usage(acc, start.data)
    merge_usage(acc, delta.data)
    # 最后非零覆盖：delta 的真实 input/cache_read 覆盖 start 的全量口径，缓存命中不再被记零。
    assert acc == {"prompt_tokens": 1, "completion_tokens": 20, "cached_prompt_tokens": 6761}


# --- OpenAI parse (pure logic, no HTTP) -------------------------------------


def test_openai_trailing_usage_frame_parsed() -> None:
    raw = json.dumps(
        {
            "id": "x",
            "choices": [],
            "usage": {"prompt_tokens": 90, "completion_tokens": 210, "prompt_tokens_details": {"cached_tokens": 30}},
        }
    )
    usage = [c for c in openai_parse(raw, {}) if c.type == "usage"]
    assert len(usage) == 1
    # OpenAI 的 prompt_tokens 含 cached_tokens，统一"未命中输入"口径后扣除：90-30=60。
    assert usage[0].data == {"prompt_tokens": 60, "completion_tokens": 210, "cached_prompt_tokens": 30}


def test_openai_content_frame_emits_no_usage_chunk() -> None:
    chunks = openai_parse(json.dumps({"choices": [{"delta": {"content": "hello"}}]}), {})
    assert all(c.type != "usage" for c in chunks)
    assert any(c.type == "text" and c.data == "hello" for c in chunks)


def test_openai_null_usage_frame_emits_no_usage_chunk() -> None:
    chunks = openai_parse(json.dumps({"choices": [{"delta": {"content": "hi"}}], "usage": None}), {})
    assert all(c.type != "usage" for c in chunks)


# --- build_payload provider-degrade switch (pure logic) ---------------------


def test_build_payload_omits_stream_options_by_default() -> None:
    assert "stream_options" not in openai_build_payload(_request(), "m", stream=True)


def test_build_payload_adds_stream_options_when_enabled() -> None:
    payload = openai_build_payload(_request(), "m", stream=True, include_usage=True)
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_no_stream_options_when_not_streaming() -> None:
    assert "stream_options" not in openai_build_payload(_request(), "m", stream=False, include_usage=True)


def test_openai_adapter_stream_usage_disabled_by_default() -> None:
    adapter = OpenAICompatAdapter(_config(ProviderType.OPENAI_COMPAT, "http://x"))
    assert "stream_options" not in adapter._build_payload(_request(), stream=True)


def test_openai_adapter_stream_usage_opt_in_via_extra_body() -> None:
    adapter = OpenAICompatAdapter(_config(ProviderType.OPENAI_COMPAT, "http://x", stream_usage=True))
    payload = adapter._build_payload(_request(), stream=True)
    assert payload["stream_options"] == {"include_usage": True}
    # the sentinel flag must not leak onto the wire as a raw request param.
    assert "stream_usage" not in payload


# --- merge_usage semantics --------------------------------------------------


def test_merge_usage_keeps_last_nonzero_per_field() -> None:
    acc = {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    merge_usage(acc, {"prompt_tokens": 10, "cached_prompt_tokens": 5})
    merge_usage(acc, {"completion_tokens": 25})
    assert acc == {"prompt_tokens": 10, "completion_tokens": 25, "cached_prompt_tokens": 5}
    merge_usage(acc, {"prompt_tokens": 0, "completion_tokens": 30})  # a later zero must not wipe prompt
    assert acc == {"prompt_tokens": 10, "completion_tokens": 30, "cached_prompt_tokens": 5}


def test_merge_usage_ignores_non_dict() -> None:
    acc = {"prompt_tokens": 7, "completion_tokens": 0, "cached_prompt_tokens": 0}
    merge_usage(acc, None)
    merge_usage(acc, "nope")
    assert acc == {"prompt_tokens": 7, "completion_tokens": 0, "cached_prompt_tokens": 0}


# --- complete_with_stream accumulation (fake adapter, no HTTP) --------------


class _UsageAdapter(LLMAdapter):
    def __init__(self, chunks: list[StreamChunk]) -> None:
        self._chunks = chunks

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - unused
        return LLMResponse(content="fallback")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        for chunk in self._chunks:
            yield chunk


class _StubLoop:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter
        self.events: list[tuple[str, Any]] = []

    def _emit(self, event_type: str, data: Any) -> None:
        self.events.append((event_type, data))


async def test_complete_with_stream_accumulates_usage_into_response() -> None:
    chunks = [
        StreamChunk(type="usage", data={"prompt_tokens": 120, "completion_tokens": 0, "cached_prompt_tokens": 40, "cache_creation_prompt_tokens": 15}),
        StreamChunk(type="text", data="hi"),
        StreamChunk(type="usage", data={"prompt_tokens": 0, "completion_tokens": 256, "cached_prompt_tokens": 0}),
        StreamChunk(type="done"),
    ]
    response = await complete_with_stream(_StubLoop(_UsageAdapter(chunks)), _request())  # type: ignore[arg-type]
    assert response.content == "hi"
    assert response.usage.prompt_tokens == 120
    assert response.usage.completion_tokens == 256
    assert response.usage.cached_prompt_tokens == 40
    assert response.usage.cache_creation_prompt_tokens == 15


# --- integration: real streaming bodies over a socket (construction a) ------


def _handler(body: bytes, content_type: str) -> type[BaseHTTPRequestHandler]:
    class _H(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # noqa: A002
            return

    return _H


@contextlib.contextmanager
def _server(handler_cls: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_OPENAI_FRAMES = [
    {"choices": [{"delta": {"content": "Hello"}}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 3}}},
]


def _openai_sse_body() -> bytes:
    parts: list[str] = []
    for frame in _OPENAI_FRAMES:
        parts.append(f"data: {json.dumps(frame)}")
        parts.append("")
    parts.extend(["data: [DONE]", ""])
    return ("\n".join(parts) + "\n").encode()


async def test_openai_stream_yields_usage_chunk_over_real_sse() -> None:
    with _server(_handler(_openai_sse_body(), "text/event-stream")) as base_url:
        adapter = OpenAICompatAdapter(_config(ProviderType.OPENAI_COMPAT, base_url))
        chunks = [c async for c in adapter.stream(_request())]
    usage = [c for c in chunks if c.type == "usage"]
    assert len(usage) == 1
    # 未命中输入口径：11 - 3(cached) = 8。
    assert usage[0].data == {"prompt_tokens": 8, "completion_tokens": 5, "cached_prompt_tokens": 3}
    assert any(c.type == "text" and c.data == "Hello" for c in chunks)


_OLLAMA_FRAMES = [
    {"message": {"content": "Hi"}, "done": False},
    {"message": {"content": ""}, "done": True, "prompt_eval_count": 33, "eval_count": 77},
]


def _ollama_body() -> bytes:
    return ("\n".join(json.dumps(frame) for frame in _OLLAMA_FRAMES) + "\n").encode()


async def test_ollama_stream_yields_usage_from_done_counts() -> None:
    with _server(_handler(_ollama_body(), "application/x-ndjson")) as base_url:
        adapter = OllamaAdapter(_config(ProviderType.OLLAMA, base_url))
        chunks = [c async for c in adapter.stream(_request())]
    usage = [c for c in chunks if c.type == "usage"]
    assert len(usage) == 1
    assert usage[0].data == {"prompt_tokens": 33, "completion_tokens": 77, "cached_prompt_tokens": 0}


_ANTHROPIC_EVENTS = [
    ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 120, "cache_read_input_tokens": 40, "output_tokens": 2}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 256}}),
    ("message_stop", {"type": "message_stop"}),
]


def _anthropic_sse_body() -> bytes:
    lines: list[str] = []
    for event_type, data in _ANTHROPIC_EVENTS:
        lines.extend([f"event: {event_type}", f"data: {json.dumps(data)}", ""])
    return ("\n".join(lines) + "\n").encode()


async def test_complete_with_stream_reports_usage_over_real_anthropic_sse() -> None:
    with _server(_handler(_anthropic_sse_body(), "text/event-stream")) as base_url:
        adapter = AnthropicAdapter(_config(ProviderType.ANTHROPIC, base_url))
        response = await complete_with_stream(_StubLoop(adapter), _request())  # type: ignore[arg-type]
    # End-to-end: real SSE -> parse -> two usage chunks -> merged onto LLMResponse.
    assert response.content == "Hello"
    assert response.usage.prompt_tokens == 120
    assert response.usage.completion_tokens == 256
    assert response.usage.cached_prompt_tokens == 40
