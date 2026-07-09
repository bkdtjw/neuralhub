from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from backend.adapters.anthropic_adapter import AnthropicAdapter
from backend.adapters.base import LLMAdapter
from backend.adapters.http_error_support import is_context_overflow
from backend.adapters.openai_adapter import OpenAICompatAdapter
from backend.common import LLMError
from backend.common.types import LLMRequest, Message, ProviderConfig, ProviderType

# Real provider overflow bodies. Anthropic surfaces the phrase in the message;
# OpenAI-compatible endpoints echo the code and/or "maximum context length".
_ANTHROPIC_OVERFLOW = (
    b'{"error": {"type": "invalid_request_error", '
    b'"message": "prompt is too long: 300000 tokens > 200000 maximum"}}'
)
_OPENAI_OVERFLOW = (
    b'{"error": {"code": "context_length_exceeded", "message": '
    b'"This model\'s maximum context length is 128000 tokens, however you '
    b'requested 200000 tokens. context_length_exceeded"}}'
)
_GENERIC_400 = b'{"error": {"message": "invalid request: unknown parameter \'widget\'"}}'


# --- pure marker matching -------------------------------------------------

@pytest.mark.parametrize(
    "message",
    [
        "prompt is too long: 300000 tokens > 200000 maximum",
        "Error code: context_length_exceeded",
        "This model's maximum context length is 8192 tokens",
        "input length and max_tokens exceed context limit",
        "PROMPT IS TOO LONG",  # case-insensitive
    ],
)
def test_is_context_overflow_true(message: str) -> None:
    assert is_context_overflow(message) is True


@pytest.mark.parametrize(
    "message",
    ["invalid request: unknown parameter 'widget'", "rate limit exceeded", ""],
)
def test_is_context_overflow_false(message: str) -> None:
    assert is_context_overflow(message) is False


# --- direct _raise_for_status ---------------------------------------------

def _config(provider_type: ProviderType, base_url: str = "https://example.com") -> ProviderConfig:
    return ProviderConfig(
        id="test",
        name="test",
        provider_type=provider_type,
        base_url=base_url,
        api_key="test-key",
        default_model="test-model",
    )


def _read_response(body: bytes) -> httpx.Response:
    # _raise_for_status always runs AFTER the body is read (post client.post()
    # for complete, post response.aread() for stream), so an already-read
    # Response is a faithful input here -- the unread-stream trap only applies
    # to the stream() entry point, exercised end-to-end below.
    return httpx.Response(
        400,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://example.com"),
    )


@pytest.mark.parametrize(
    "adapter_cls,provider_type,body,expected",
    [
        (OpenAICompatAdapter, ProviderType.OPENAI_COMPAT, _OPENAI_OVERFLOW, "CONTEXT_OVERFLOW"),
        (AnthropicAdapter, ProviderType.ANTHROPIC, _ANTHROPIC_OVERFLOW, "CONTEXT_OVERFLOW"),
        (OpenAICompatAdapter, ProviderType.OPENAI_COMPAT, _GENERIC_400, "API_ERROR"),
        (AnthropicAdapter, ProviderType.ANTHROPIC, _GENERIC_400, "API_ERROR"),
    ],
)
def test_raise_for_status_classifies_overflow(
    adapter_cls: type[LLMAdapter], provider_type: ProviderType, body: bytes, expected: str
) -> None:
    adapter = adapter_cls(_config(provider_type))
    with pytest.raises(LLMError) as exc_info:
        adapter._raise_for_status(_read_response(body))  # noqa: SLF001
    assert exc_info.value.code == expected
    assert exc_info.value.status_code == 400


# --- end-to-end over a genuinely-unread streaming body --------------------

def _handler_for(body: bytes) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # noqa: A002
            return

    return _Handler


@contextlib.contextmanager
def _error_server(body: bytes) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(body))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request() -> LLMRequest:
    return LLMRequest(model="test-model", messages=[Message(role="user", content="hi")])


async def _stream_error(adapter: LLMAdapter) -> LLMError:
    with pytest.raises(LLMError) as exc_info:
        async for _chunk in adapter.stream(_request()):
            pass
    return exc_info.value


@pytest.mark.asyncio
async def test_openai_stream_overflow_yields_context_overflow() -> None:
    with _error_server(_OPENAI_OVERFLOW) as base_url:
        error = await _stream_error(
            OpenAICompatAdapter(_config(ProviderType.OPENAI_COMPAT, base_url))
        )
    assert error.code == "CONTEXT_OVERFLOW"
    assert error.status_code == 400
    assert "maximum context length" in error.message


@pytest.mark.asyncio
async def test_anthropic_stream_overflow_yields_context_overflow() -> None:
    with _error_server(_ANTHROPIC_OVERFLOW) as base_url:
        error = await _stream_error(AnthropicAdapter(_config(ProviderType.ANTHROPIC, base_url)))
    assert error.code == "CONTEXT_OVERFLOW"
    assert error.status_code == 400
    assert "prompt is too long" in error.message
