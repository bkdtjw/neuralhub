from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, LLMUsage, Message, ProviderConfig, StreamChunk

from .base import LLMAdapter
from .logging_support import (
    adapter_logger,
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_start,
)
from .message_zones import request_system_prompt, request_zone_messages

logger = adapter_logger("claude_code_adapter")
_TIMEOUT_SECONDS = 300.0
# 全量禁用内建工具：本 provider 只当纯文本 LLM 用；claude CLI 以 root 跑在服务器上，
# 不禁则经 /v1 入口（尚无鉴权）会变成远程文件读取器。
_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task,Agent,"
    "TodoWrite,Skill,SlashCommand,KillShell,BashOutput,EnterPlanMode,ExitPlanMode"
)


def _render_message(message: Message) -> str:
    parts: list[str] = []
    text = (message.content or "").strip()
    if text:
        parts.append(f"[{message.role}] {text}")
    for call in message.tool_calls or []:
        parts.append(f"[{message.role} 调用工具 {call.name}] {json.dumps(call.arguments, ensure_ascii=False)}")
    for result in message.tool_results or []:
        parts.append(f"[工具结果] {result.output}")
    return "\n".join(parts)


def _render_prompt(request: LLMRequest) -> str:
    rendered = [_render_message(m) for m in request_zone_messages(request, include_system=False)]
    body = "\n\n".join(part for part in rendered if part)
    return f"{body}\n\n请以 assistant 身份直接回复最后一条 user 消息。"


def _parse_result(raw: str, provider: str) -> LLMResponse:
    try:
        data: dict[str, Any] = json.loads(raw)
    except ValueError as exc:
        raise LLMError("CLAUDE_CODE_PARSE_ERROR", f"invalid JSON from CLI: {raw[:200]}", provider) from exc
    if data.get("is_error"):
        raise LLMError("CLAUDE_CODE_ERROR", str(data.get("result", ""))[:500], provider)
    usage = LLMUsage()
    for stats in (data.get("modelUsage") or {}).values():
        if isinstance(stats, dict):
            usage.prompt_tokens += int(stats.get("inputTokens", 0) or 0)
            usage.completion_tokens += int(stats.get("outputTokens", 0) or 0)
            usage.cached_prompt_tokens += int(stats.get("cacheReadInputTokens", 0) or 0)
            usage.cache_creation_prompt_tokens += int(stats.get("cacheCreationInputTokens", 0) or 0)
    return LLMResponse(content=str(data.get("result", "")), usage=usage)


class ClaudeCodeAdapter(LLMAdapter):
    """经本机 claude CLI 无头模式（-p --output-format json）调用，走订阅额度而非 API 计费。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._command = config.base_url.strip() or "claude"
        self._default_model = config.default_model
        self._provider = config.provider_type.value
        extra = config.extra_body if isinstance(config.extra_body, dict) else {}
        self._home = str(extra.get("home") or "")
        # 在空目录运行，避免继承宿主项目的 CLAUDE.md / MCP 配置
        self._cwd = str(extra.get("cwd") or tempfile.gettempdir())

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._home:
            env["HOME"] = self._home
        return env

    def _ensure_home_config(self) -> None:
        # CLI 要求 $HOME/.claude.json 存在（容器内首跑没有且因 backups 存在而拒绝自建），补种最小配置
        if not self._home:
            return
        path = Path(self._home) / ".claude.json"
        try:
            if not path.exists():
                path.write_text('{"hasCompletedOnboarding": true}', encoding="utf-8")
        except OSError:
            logger.warning("claude_code_home_seed_failed", path=str(path))

    def _args(self, request: LLMRequest) -> list[str]:
        args = [
            self._command,
            "-p",
            "--output-format",
            "json",
            "--model",
            request.model or self._default_model,
            "--disallowedTools",
            _DISALLOWED_TOOLS,
        ]
        system_prompt = request_system_prompt(request)
        if system_prompt:
            args.extend(["--system-prompt", system_prompt])
        return args

    async def _run(self, request: LLMRequest) -> LLMResponse:
        self._ensure_home_config()
        proc = await asyncio.create_subprocess_exec(
            *self._args(request),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=_render_prompt(request).encode("utf-8")),
                timeout=_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise LLMError(
                "CLAUDE_CODE_TIMEOUT", f"claude CLI timed out after {int(_TIMEOUT_SECONDS)}s", self._provider
            ) from exc
        if proc.returncode != 0:
            detail = (stderr or stdout or b"").decode("utf-8", "replace")[-500:]
            raise LLMError("CLAUDE_CODE_ERROR", f"exit {proc.returncode}: {detail}", self._provider)
        return _parse_result(stdout.decode("utf-8", "replace"), self._provider)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started_at = log_llm_request_start(
            logger, model=request.model, provider=self._provider, request_type="complete"
        )
        try:
            response = await self._run(request)
        except LLMError as exc:
            log_llm_request_error(
                logger, model=request.model, provider=self._provider,
                request_type="complete", exc=exc, started_at=started_at,
            )
            await incr_llm_error()
            raise
        except Exception as exc:
            error = LLMError("CLAUDE_CODE_ERROR", str(exc), self._provider)
            log_llm_request_error(
                logger, model=request.model, provider=self._provider,
                request_type="complete", exc=error, started_at=started_at,
            )
            await incr_llm_error()
            raise error from exc
        log_llm_request_end(
            logger, model=request.model, provider=self._provider,
            request_type="complete", started_at=started_at, response=response,
        )
        await incr_llm_success(response)
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        # CLI 的 stream-json 是会话事件流而非增量 token，此处伪流式：整段一次吐出
        response = await self.complete(request)
        yield StreamChunk(type="usage", data=response.usage.model_dump())
        if response.content:
            yield StreamChunk(type="text", data=response.content)
        yield StreamChunk(type="done")

    async def test_connection(self) -> bool:
        try:
            self._ensure_home_config()
            proc = await asyncio.create_subprocess_exec(
                self._command, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd, env=self._env(),
            )
            await asyncio.wait_for(proc.communicate(), timeout=30.0)
            return proc.returncode == 0
        except LLMError:
            raise
        except Exception as exc:
            logger.warning("claude_code_test_connection_failed", error=str(exc))
            return False


__all__ = ["ClaudeCodeAdapter"]
