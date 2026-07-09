from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from backend.adapters.anthropic_adapter import AnthropicAdapter
from backend.adapters.anthropic_stream import parse_stream_line
from backend.adapters.anthropic_support import build_payload
from backend.adapters.base import LLMAdapter
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ProviderConfig,
    ProviderType,
    StreamChunk,
)
from backend.core.s01_agent_loop.streaming import complete_with_stream


def _request(*, thinking: bool, max_tokens: int = 16384, temperature: float = 0.7) -> LLMRequest:
    return LLMRequest(
        model="claude-3-7-sonnet",
        messages=[Message(role="user", content="hi")],
        thinking=thinking,
        max_tokens=max_tokens,
        temperature=temperature,
    )


# --- payload construction (pure logic, no HTTP) -----------------------------


def test_thinking_forces_temperature_one_and_valid_budget() -> None:
    payload = build_payload(_request(thinking=True), "claude-3-7-sonnet", stream=False)
    budget = payload["thinking"]["budget_tokens"]
    # Anthropic rejects any temperature != 1 while extended thinking is enabled.
    assert payload["temperature"] == 1.0
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert budget >= 1024
    assert budget < payload["max_tokens"]


def test_thinking_budget_bumps_max_tokens_when_too_small() -> None:
    # max_tokens below the 1024 floor must still yield budget>=1024 AND
    # max_tokens>budget, otherwise Anthropic 400s on the constraint itself.
    payload = build_payload(_request(thinking=True, max_tokens=1000), "claude-3-7-sonnet", stream=False)
    budget = payload["thinking"]["budget_tokens"]
    assert budget == 1024
    assert budget >= 1024
    assert payload["max_tokens"] == 1025
    assert budget < payload["max_tokens"]


def test_thinking_budget_stays_below_medium_max_tokens() -> None:
    payload = build_payload(_request(thinking=True, max_tokens=3000), "claude-3-7-sonnet", stream=False)
    budget = payload["thinking"]["budget_tokens"]
    assert budget == 2999
    assert budget < payload["max_tokens"] == 3000


def test_no_thinking_preserves_request_temperature() -> None:
    payload = build_payload(_request(thinking=False, temperature=0.3), "claude-3-7-sonnet", stream=False)
    assert payload["temperature"] == 0.3
    assert "thinking" not in payload


# --- streaming signature collection -----------------------------------------


def test_stream_parser_accumulates_thinking_signature() -> None:
    thinking_blocks: dict[int, dict[str, Any]] = {}
    start = {"index": 0, "content_block": {"type": "thinking", "thinking": ""}}
    think = {"index": 0, "delta": {"type": "thinking_delta", "thinking": "Let me reason. "}}
    sign = {"index": 0, "delta": {"type": "signature_delta", "signature": "SIG-abc123"}}

    assert parse_stream_line("content_block_start", json.dumps(start), "anthropic", None, thinking_blocks) is None
    reasoning = parse_stream_line("content_block_delta", json.dumps(think), "anthropic", None, thinking_blocks)
    assert reasoning is not None and reasoning.type == "reasoning" and reasoning.data == "Let me reason. "
    assert parse_stream_line("content_block_delta", json.dumps(sign), "anthropic", None, thinking_blocks) is None

    stop = parse_stream_line("content_block_stop", json.dumps({"index": 0}), "anthropic", None, thinking_blocks)
    assert stop is not None
    assert stop.type == "reasoning"
    assert stop.data == {
        "type": "thinking",
        "thinking": "Let me reason. ",
        "signature": "SIG-abc123",
    }
    # Block is consumed once emitted so it cannot be re-sent.
    assert thinking_blocks == {}


_SSE_EVENTS = [
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Reasoning "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG-xyz789"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Hello"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_stop", {"type": "message_stop"}),
]


def _sse_body() -> bytes:
    lines: list[str] = []
    for event_type, data in _SSE_EVENTS:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


class _ThinkingSSEHandler(BaseHTTPRequestHandler):
    """Serve a real 200 SSE stream over a socket -- construction (a).

    The adapter consumes it through ``client.stream()`` + ``aiter_lines()``,
    so the signature must survive an actual chunked read rather than a
    pre-populated ``MockTransport(content=...)`` body.
    """

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        body = _sse_body()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def _sse_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ThinkingSSEHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_adapter_stream_surfaces_signature_block() -> None:
    with _sse_server() as base_url:
        adapter = AnthropicAdapter(
            ProviderConfig(
                id="anthropic",
                name="anthropic",
                provider_type=ProviderType.ANTHROPIC,
                base_url=base_url,
                api_key="test-key",
                default_model="claude-3-7-sonnet",
            )
        )
        chunks = [chunk async for chunk in adapter.stream(_request(thinking=True))]

    blocks = [chunk.data for chunk in chunks if chunk.type == "reasoning" and isinstance(chunk.data, dict)]
    assert len(blocks) == 1
    assert blocks[0] == {"type": "thinking", "thinking": "Reasoning ", "signature": "SIG-xyz789"}
    assert any(chunk.type == "text" and chunk.data == "Hello" for chunk in chunks)


class _SignatureAdapter(LLMAdapter):
    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - unused
        return LLMResponse(content="fallback")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="reasoning", data="Reasoning ")
        yield StreamChunk(
            type="reasoning",
            data={"type": "thinking", "thinking": "Reasoning ", "signature": "SIG-round-trip"},
        )
        yield StreamChunk(type="text", data="answer")
        yield StreamChunk(type="done")


class _StubLoop:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter
        self.events: list[tuple[str, Any]] = []

    def _emit(self, event_type: str, data: Any) -> None:
        self.events.append((event_type, data))


async def test_complete_with_stream_round_trips_signature() -> None:
    loop = _StubLoop(_SignatureAdapter())
    response = await complete_with_stream(loop, _request(thinking=True))  # type: ignore[arg-type]

    blocks = response.provider_metadata["thinking_blocks"]
    assert blocks == [{"type": "thinking", "thinking": "Reasoning ", "signature": "SIG-round-trip"}]
    assert response.provider_metadata["reasoning_content"] == "Reasoning "
    assert response.content == "answer"
    # Live reasoning text is still streamed to the UI alongside the block.
    assert ("reasoning_delta", "Reasoning ") in loop.events
