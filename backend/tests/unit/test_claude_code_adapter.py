"""ClaudeCodeAdapter：CLI JSON 解析、伪流式、错误/超时、并发闸、取消杀进程组、工厂与探测接线。"""

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
        "claude-fable-5": {"inputTokens": 2, "outputTokens": 22, "cacheReadInputTokens": 25774, "cacheCreationInputTokens": 1200},
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
    _next_pid = 4000

    def __init__(self, stdout: bytes, returncode: int = 0, stderr: bytes = b"", delay: float = 0.0) -> None:
        self.stdout_data, self.returncode = stdout, returncode
        self.stderr_data, self.delay = stderr, delay
        self.stdin_payload: bytes | None = None
        _FakeProc._next_pid += 1
        self.pid = _FakeProc._next_pid

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_payload = input
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.stdout_data, self.stderr_data

    async def wait(self) -> int:
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def _install(
    monkeypatch: pytest.MonkeyPatch, *procs: _FakeProc
) -> tuple[list[list[str]], list[dict[str, Any]], list[tuple[int, int]]]:
    """装配子进程与信号打桩；返回 (argv 列表, kwargs 列表, killpg 调用 [(pgid, sig)])。"""
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []
    killed: list[tuple[int, int]] = []
    queue = list(procs)

    async def fake_exec(*args: str, **kwargs: Any) -> _FakeProc:
        calls.append(list(args))
        kwargs_seen.append(kwargs)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(claude_code_adapter.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(claude_code_adapter.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(claude_code_adapter.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    return calls, kwargs_seen, killed


async def test_complete_parses_content_usage_and_cli_args(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(json.dumps(_CLI_RESULT).encode())
    calls, kwargs_seen, _ = _install(monkeypatch, proc)
    response = await ClaudeCodeAdapter(_config()).complete(_request())
    assert response.content == "你好！"
    assert response.usage.prompt_tokens == 523
    assert response.usage.completion_tokens == 34
    assert response.usage.cached_prompt_tokens == 25774
    assert response.usage.cache_creation_prompt_tokens == 1200
    args = calls[0]
    assert args[0] == "claude"
    assert args[1] == "-p"
    assert args[args.index("--model") + 1] == "claude-opus-5"
    assert "Bash" in args[args.index("--disallowedTools") + 1]
    assert args[args.index("--system-prompt") + 1] == "你是测试助手"
    assert kwargs_seen[0]["env"]["HOME"] == "/root"
    assert kwargs_seen[0]["start_new_session"] is True
    assert proc.stdin_payload is not None
    assert "[user] 你好" in proc.stdin_payload.decode()


async def test_builtin_tools_disabled_and_session_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """--tools "" 把 CLI 自带前缀从约 2 万 token 压到百量级，是这个 provider 的主要省钱项。"""
    calls, _, _ = _install(monkeypatch, _FakeProc(json.dumps(_CLI_RESULT).encode()))
    await ClaudeCodeAdapter(_config()).complete(_request())
    args = calls[0]
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args


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


async def test_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(b"", returncode=None, delay=5.0)
    _, _, killed = _install(monkeypatch, proc)
    monkeypatch.setattr(claude_code_adapter, "_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(LLMError) as exc_info:
        await ClaudeCodeAdapter(_config()).complete(_request())
    assert exc_info.value.code == "CLAUDE_CODE_TIMEOUT"
    assert killed and killed[0] == (proc.pid, claude_code_adapter.signal.SIGTERM)


async def test_cancellation_kills_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """客户端断连触发取消时必须杀掉整组，否则 CLI 跑完整轮、白烧订阅额度。"""
    proc = _FakeProc(b"", returncode=None, delay=5.0)
    _, _, killed = _install(monkeypatch, proc)
    task = asyncio.create_task(ClaudeCodeAdapter(_config()).complete(_request()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed and killed[0] == (proc.pid, claude_code_adapter.signal.SIGTERM)


async def test_semaphore_caps_concurrent_cli_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 核机器上并发起 CLI 会压垮内存，适配器须自带并发闸。"""
    running = 0
    peak = 0

    class _TrackingProc(_FakeProc):
        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            return self.stdout_data, self.stderr_data

    procs = [_TrackingProc(json.dumps(_CLI_RESULT).encode()) for _ in range(4)]
    _install(monkeypatch, *procs)
    adapter = ClaudeCodeAdapter(_config(extra_body={"home": "/root", "max_concurrency": 2}))
    await asyncio.gather(*(adapter.complete(_request()) for _ in range(4)))
    assert peak == 2


async def test_strips_upstream_anthropic_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://other.example/compat/v4")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-other")
    _, kwargs_seen, _ = _install(monkeypatch, _FakeProc(json.dumps(_CLI_RESULT).encode()))
    await ClaudeCodeAdapter(_config()).complete(_request())
    env = kwargs_seen[0]["env"]
    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["HOME"] == "/root"


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
