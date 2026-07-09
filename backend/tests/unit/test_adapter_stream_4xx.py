from __future__ import annotations

import contextlib
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from backend.adapters.anthropic_adapter import AnthropicAdapter
from backend.adapters.base import LLMAdapter
from backend.adapters.http_error_support import error_message
from backend.adapters.ollama_adapter import OllamaAdapter
from backend.adapters.openai_adapter import OpenAICompatAdapter
from backend.common import LLMError
from backend.common.types import LLMRequest, Message, ProviderConfig, ProviderType

# Generic (non-overflow) 4xx body; the substring below is what must survive to
# the caller. A context-overflow phrase is deliberately avoided here so this
# H1 body-survival test stays decoupled from the H4 CONTEXT_OVERFLOW
# classification (covered in test_context_overflow_code.py).
_ERROR_BODY = b'{"error": {"message": "invalid request: unknown parameter \'widget\'"}}'


class _StreamingErrorHandler(BaseHTTPRequestHandler):
    """Serve a real 400 + JSON body over a socket.

    Construction (a) from the task brief: because the adapter issues the
    request via ``client.stream()``, httpx leaves the body unread until
    ``aread()`` / ``aiter_*`` runs -- so ``response.json()`` / ``.text`` raise
    ``httpx.ResponseNotRead``, faithfully reproducing production. This is what
    ``httpx.MockTransport(content=...)`` cannot do (it pre-populates
    ``_content``, making both buggy and fixed code look green).
    """

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_ERROR_BODY)))
        self.end_headers()
        self.wfile.write(_ERROR_BODY)

    def log_message(self, *args: object) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def _error_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StreamingErrorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config(provider_type: ProviderType, base_url: str) -> ProviderConfig:
    return ProviderConfig(
        id="test",
        name="test",
        provider_type=provider_type,
        base_url=base_url,
        api_key="test-key",
        default_model="test-model",
    )


def _request() -> LLMRequest:
    return LLMRequest(model="test-model", messages=[Message(role="user", content="hi")])


async def _stream_error(adapter: LLMAdapter) -> LLMError:
    with pytest.raises(LLMError) as exc_info:
        async for _chunk in adapter.stream(_request()):
            pass
    return exc_info.value


@pytest.mark.asyncio
async def test_openai_stream_4xx_surfaces_api_error() -> None:
    with _error_server() as base_url:
        error = await _stream_error(OpenAICompatAdapter(_config(ProviderType.OPENAI_COMPAT, base_url)))
    assert error.code == "API_ERROR"
    assert error.status_code == 400
    assert "unknown parameter" in error.message


@pytest.mark.asyncio
async def test_anthropic_stream_4xx_surfaces_api_error() -> None:
    with _error_server() as base_url:
        error = await _stream_error(AnthropicAdapter(_config(ProviderType.ANTHROPIC, base_url)))
    assert error.code == "API_ERROR"
    assert error.status_code == 400
    assert "unknown parameter" in error.message


@pytest.mark.asyncio
async def test_ollama_stream_4xx_surfaces_api_error() -> None:
    with _error_server() as base_url:
        error = await _stream_error(OllamaAdapter(_config(ProviderType.OLLAMA, base_url)))
    assert error.code == "API_ERROR"
    assert error.status_code == 400
    assert "unknown parameter" in error.message


class _UnreadAsyncStream(httpx.AsyncByteStream):
    """A never-consumed async body -- construction (c) from the task brief."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield _ERROR_BODY


def test_error_message_defensive_fallback_on_unread_stream() -> None:
    response = httpx.Response(
        400,
        stream=_UnreadAsyncStream(),
        request=httpx.Request("POST", "http://test/v1/messages"),
    )
    # Prove the body is genuinely unread: .text raises ResponseNotRead here,
    # so error_message must not re-raise it (the double-insurance fallback).
    with pytest.raises(httpx.ResponseNotRead):
        _ = response.text
    assert error_message(response) == "HTTP 400"
