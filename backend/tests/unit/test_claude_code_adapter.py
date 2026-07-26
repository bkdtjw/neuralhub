"""ClaudeCodeAdapter：CLI JSON 解析、伪流式、错误/超时、工厂与探测接线。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.adapters import claude_code_adapter, model_discovery
from backend.adapters.claude_code_adapter import ClaudeCodeAdapter
from backend.adapters.factory import AdapterFactory
from backend.common import LLMError
from backend.common.types import LLMRequest, Message, ProviderConfig

_CLI_RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "你好！",
    "total_cost_usd": 0.51,
    "modelUsage": {
        "claude-haiku-4-5-20251001": {"inputTokens": 521, "outputTokens": 12, "cacheReadInputTokens": 0},
        "claude-fable-5": {"inputTokens": 2, "outputTokens": 22, "cacheReadInputTokens": 25774},
    },
}


def _config(**overrides: Any) -> ProviderConfig:
    data: dict[str, Any] = {
        "id": "cc",
        "name": "Claude Code",
        "provider_type": "claude_code",
        "base_url": "",
        "api_key": "",
        "default_model": "claude-fable-5",
        "extra_body": {"home": "/root"},
    }
    data.update(overrides)
    return ProviderConfig(**data)


def _request() -> LLMRequest:
    return LLMRequest(
        model="claude-opus-5",
        system_prompt="你是测试助手",
        recent_messages=[Message(role="user", content="你好")],
    )


class _FakeProc:
    def __init__(self, stdout: bytes, returncode: int = 0, stderr: bytes = b"", delay: float = 0.0) -> None:
        self.stdout_data, self.returncode = stdout, returncode
        self.stderr_data, self.delay = stderr, delay
        self.killed = False
        self.stdin_payload: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_payload = input
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.stdout_data, self.stderr_data

    def kill(self) -> None:
        self.killed = True


def _install(
    monkeypatch: pytest.MonkeyPatch, proc: _FakeProc
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []

    async def fake_exec(*args: str, **kwargs: Any) -> _FakeProc:
        calls.append(list(args))
        kwargs_seen.append(kwargs)
        return proc

    monkeypatch.setattr(claude_code_adapter.asyncio, "create_subprocess_exec", fake_exec)
    return calls, kwargs_seen


async def test_complete_parses_content_usage_and_cli_args(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(json.dumps(_CLI_RESULT).encode())
    calls, kwargs_seen = _install(monkeypatch, proc)
    response = await ClaudeCodeAdapter(_config()).complete(_request())
    assert response.content == "你好！"
    assert response.usage.prompt_tokens == 523
    assert response.usage.completion_tokens == 34
    assert response.usage.cached_prompt_tokens == 25774
    args = calls[0]
    assert args[0] == "claude"
    assert args[1] == "-p"
    assert args[args.index("--model") + 1] == "claude-opus-5"
    assert "Bash" in args[args.index("--disallowedTools") + 1]
    assert args[args.index("--system-prompt") + 1] == "你是测试助手"
    assert kwargs_seen[0]["env"]["HOME"] == "/root"
    assert proc.stdin_payload is not None
    assert "[user] 你好" in proc.stdin_payload.decode()


async def test_stream_yields_usage_text_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeProc(json.dumps(_CLI_RESULT).encode()))
    chunks = [chunk async for chunk in ClaudeCodeAdapter(_config()).stream(_request())]
    assert [chunk.type for chunk in chunks] == ["usage", "text", "done"]
    assert chunks[0].data["cached_prompt_tokens"] == 25774
    assert chunks[1].data == "你好！"


async def test_nonzero_exit_raises_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeProc(b"", returncode=1, stderr=b"boom"))
    with pytest.raises(LLMError) as exc_info:
        await ClaudeCodeAdapter(_config()).complete(_request())
    assert exc_info.value.code == "CLAUDE_CODE_ERROR"
    assert "boom" in exc_info.value.message


async def test_is_error_result_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"is_error": True, "result": "usage limit reached"}
    _install(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    with pytest.raises(LLMError) as exc_info:
        await ClaudeCodeAdapter(_config()).complete(_request())
    assert "usage limit" in exc_info.value.message


async def test_timeout_kills_process(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(b"", delay=5.0)
    _install(monkeypatch, proc)
    monkeypatch.setattr(claude_code_adapter, "_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(LLMError) as exc_info:
        await ClaudeCodeAdapter(_config()).complete(_request())
    assert exc_info.value.code == "CLAUDE_CODE_TIMEOUT"
    assert proc.killed is True


async def test_test_connection_uses_version_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(b"2.1.215 (Claude Code)")
    calls, _ = _install(monkeypatch, proc)
    assert await ClaudeCodeAdapter(_config()).test_connection() is True
    assert calls[0] == ["claude", "--version"]


async def test_seeds_home_config_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _install(monkeypatch, _FakeProc(b"2.1.215 (Claude Code)"))
    adapter = ClaudeCodeAdapter(_config(extra_body={"home": str(tmp_path)}))
    assert await adapter.test_connection() is True
    seeded = (tmp_path / ".claude.json").read_text(encoding="utf-8")
    assert json.loads(seeded) == {"hasCompletedOnboarding": True}


def test_factory_creates_claude_code_adapter() -> None:
    adapter = AdapterFactory.create(_config())
    assert isinstance(adapter, ClaudeCodeAdapter)


async def test_discovery_returns_static_model_list() -> None:
    models = await model_discovery.discover_models("claude_code", "", "")
    assert "claude-fable-5" in models
    assert "claude-opus-5" in models
