from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.adapters.anthropic_adapter import AnthropicAdapter
from backend.adapters.ollama_adapter import OllamaAdapter
from backend.adapters.openai_adapter import OpenAICompatAdapter
from backend.common import LLMError
from backend.common.types import LLMRequest, Message, ProviderConfig, ProviderType

# 本文件测的是 HTTP 适配器契约（mock httpx）；claude_code 是子进程型适配器，不适用
_HTTP_PROVIDER_TYPES = [ProviderType.OPENAI_COMPAT, ProviderType.ANTHROPIC, ProviderType.OLLAMA]


def _provider(provider_type: ProviderType) -> ProviderConfig:
    return ProviderConfig(
        id=f"{provider_type.value}-id",
        name=provider_type.value,
        provider_type=provider_type,
        base_url="https://example.com",
        api_key="",
        default_model="test-model",
        available_models=["test-model"],
    )


def _adapter(provider_type: ProviderType) -> OpenAICompatAdapter | AnthropicAdapter | OllamaAdapter:
    if provider_type == ProviderType.ANTHROPIC:
        return AnthropicAdapter(_provider(provider_type))
    if provider_type == ProviderType.OLLAMA:
        return OllamaAdapter(_provider(provider_type))
    return OpenAICompatAdapter(_provider(provider_type))


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.com")


def _success_response(provider_type: ProviderType) -> httpx.Response:
    payloads = {
        ProviderType.OPENAI_COMPAT: {
            "id": "resp-1",
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        },
        ProviderType.ANTHROPIC: {
            "id": "resp-2",
            "content": [{"type": "text", "text": "answer"}],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
        ProviderType.OLLAMA: {
            "message": {"content": "answer"},
            "prompt_eval_count": 1,
            "eval_count": 2,
        },
    }
    return httpx.Response(200, json=payloads[provider_type], request=_request())


def _error_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, json={"error": {"message": "boom"}}, request=_request())


def _llm_request() -> LLMRequest:
    return LLMRequest(model="test-model", messages=[Message(role="user", content="hello")])


def test_openai_adapter_round_trips_reasoning_content() -> None:
    adapter = OpenAICompatAdapter(_provider(ProviderType.OPENAI_COMPAT))
    messages = adapter._to_openai_messages([Message(role="assistant", content="answer", provider_metadata={"reasoning_content": "step"})])  # noqa: SLF001
    response = adapter._parse_response(  # noqa: SLF001
        {
            "id": "resp-1",
            "choices": [{"message": {"content": "answer", "reasoning_content": "step"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }
    )
    assert messages[0]["reasoning_content"] == "step"
    assert response.provider_metadata["reasoning_content"] == "step"


def test_anthropic_adapter_round_trips_thinking_blocks() -> None:
    adapter = AnthropicAdapter(_provider(ProviderType.ANTHROPIC))
    messages = adapter._to_anthropic_messages(  # noqa: SLF001
        [Message(role="assistant", content="answer", provider_metadata={"thinking_blocks": [{"type": "thinking", "thinking": "step"}]})]
    )
    response = adapter._parse_response(  # noqa: SLF001
        {
            "id": "resp-2",
            "content": [{"type": "thinking", "thinking": "step"}, {"type": "text", "text": "answer"}],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    )
    assert messages[0]["content"][0]["type"] == "thinking"
    assert response.provider_metadata["thinking"] == "step"
    assert response.provider_metadata["thinking_blocks"][0]["type"] == "thinking"


def test_anthropic_adapter_uses_v1_messages_for_compat_base_url() -> None:
    provider = _provider(ProviderType.ANTHROPIC).model_copy(
        update={"base_url": "https://open.bigmodel.cn/api/anthropic"}
    )
    adapter = AnthropicAdapter(provider)
    assert adapter._url == "https://open.bigmodel.cn/api/anthropic/v1/messages"  # noqa: SLF001


def test_ollama_adapter_parses_reasoning_content() -> None:
    adapter = OllamaAdapter(_provider(ProviderType.OLLAMA))
    response = adapter._parse_response(  # noqa: SLF001
        {"message": {"content": "answer", "reasoning_content": "step"}, "prompt_eval_count": 1, "eval_count": 2}
    )
    assert response.provider_metadata["reasoning_content"] == "step"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", _HTTP_PROVIDER_TYPES)
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
async def test_complete_retries_on_retryable_status_codes(provider_type: ProviderType, status_code: int, caplog: pytest.LogCaptureFixture) -> None:
    adapter = _adapter(provider_type)
    with caplog.at_level(logging.WARNING), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, patch("backend.adapters.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch("backend.adapters.base.random.uniform", return_value=0.0):
        mock_post.side_effect = [_error_response(status_code), _success_response(provider_type)]
        response = await adapter.complete(_llm_request())
    assert response.content == "answer"
    assert mock_post.await_count == 2
    mock_sleep.assert_awaited_once()
    assert "llm_request_retry" in caplog.text
    assert "llm_request_retry_wait" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", _HTTP_PROVIDER_TYPES)
@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError],
)
async def test_complete_retries_on_retryable_request_errors(provider_type: ProviderType, error_type: type[Exception]) -> None:
    adapter = _adapter(provider_type)
    network_error = error_type("boom", request=_request())
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, patch("backend.adapters.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch("backend.adapters.base.random.uniform", return_value=0.0):
        mock_post.side_effect = [network_error, _success_response(provider_type)]
        response = await adapter.complete(_llm_request())
    assert response.content == "answer"
    assert mock_post.await_count == 2
    mock_sleep.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", _HTTP_PROVIDER_TYPES)
@pytest.mark.parametrize("status_code,error_code", [(400, "API_ERROR"), (401, "AUTH_ERROR"), (403, "API_ERROR"), (404, "API_ERROR")])
async def test_complete_does_not_retry_on_non_retryable_status_codes(provider_type: ProviderType, status_code: int, error_code: str) -> None:
    adapter = _adapter(provider_type)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, patch("backend.adapters.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_post.return_value = _error_response(status_code)
        with pytest.raises(LLMError) as exc_info:
            await adapter.complete(_llm_request())
    assert exc_info.value.code == error_code
    assert mock_post.await_count == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_anthropic_complete_raises_on_success_false_body() -> None:
    adapter = AnthropicAdapter(_provider(ProviderType.ANTHROPIC))
    bad_body = httpx.Response(
        200,
        json={"code": 500, "msg": "404 NOT_FOUND", "success": False},
        request=_request(),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = bad_body
        with pytest.raises(LLMError) as exc_info:
            await adapter.complete(_llm_request())
    assert exc_info.value.code == "API_ERROR"
    assert "404 NOT_FOUND" in exc_info.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", _HTTP_PROVIDER_TYPES)
async def test_complete_exhausts_retries_on_server_error(provider_type: ProviderType) -> None:
    adapter = _adapter(provider_type)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, patch("backend.adapters.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch("backend.adapters.base.random.uniform", return_value=0.0):
        mock_post.side_effect = [_error_response(500), _error_response(500), _error_response(500)]
        with pytest.raises(LLMError) as exc_info:
            await adapter.complete(_llm_request())
    assert exc_info.value.code == "SERVER_ERROR"
    assert mock_post.await_count == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", _HTTP_PROVIDER_TYPES)
async def test_complete_exhausts_retries_on_network_error(provider_type: ProviderType) -> None:
    adapter = _adapter(provider_type)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, patch("backend.adapters.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch("backend.adapters.base.random.uniform", return_value=0.0):
        mock_post.side_effect = [httpx.ConnectTimeout("boom", request=_request()) for _ in range(3)]
        with pytest.raises(LLMError) as exc_info:
            await adapter.complete(_llm_request())
    assert exc_info.value.code == "NETWORK_ERROR"
    assert mock_post.await_count == 3
    assert mock_sleep.await_count == 2


def test_retry_delay_increases_with_attempts() -> None:
    adapter = OpenAICompatAdapter(_provider(ProviderType.OPENAI_COMPAT))
    with patch("backend.adapters.base.random.uniform", return_value=0.0):
        assert adapter._retry_delay(1) < adapter._retry_delay(2) < adapter._retry_delay(3)  # noqa: SLF001
        assert adapter._retry_delay(10) == 10.0  # noqa: SLF001
