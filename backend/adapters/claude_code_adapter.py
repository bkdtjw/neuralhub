from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import tempfile
from collections.abc import AsyncIterator

from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, ProviderConfig, StreamChunk

from .base import LLMAdapter
from .claude_code_support import (
    build_args,
    build_env,
    ensure_home_config,
    parse_result,
    render_prompt,
)
from .logging_support import (
    adapter_logger,
    incr_llm_error,
    incr_llm_success,
    log_llm_request_end,
    log_llm_request_error,
    log_llm_request_start,
)

logger = adapter_logger("claude_code_adapter")
_TIMEOUT_SECONDS = 300.0
_TERMINATE_GRACE_SECONDS = 3.0
# 每个 CLI 子进程是完整 node 进程（数百 MB），生产机仅 2 核 3.5G 且有过并发压死记录，
# 故默认只允许 2 个并发；排队等待不计入 _TIMEOUT_SECONDS，避免排队被误报超时。
_DEFAULT_MAX_CONCURRENCY = 2


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
        limit = int(extra.get("max_concurrency") or _DEFAULT_MAX_CONCURRENCY)
        self._semaphore = asyncio.Semaphore(max(1, limit))

    async def _spawn(self, request: LLMRequest) -> asyncio.subprocess.Process:
        ensure_home_config(self._home, logger)
        return await asyncio.create_subprocess_exec(
            *build_args(self._command, request, self._default_model),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=build_env(self._home),
            # 独立进程组：CLI 会派生 node 子进程，只杀主进程会留下孤儿继续跑满额度
            start_new_session=True,
        )

    async def _kill_process_group(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(proc.pid), sig)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_SECONDS)
                return
        with contextlib.suppress(Exception):
            await proc.wait()

    async def _communicate(self, proc: asyncio.subprocess.Process, request: LLMRequest) -> LLMResponse:
        payload = render_prompt(request).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=payload), timeout=_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            await self._kill_process_group(proc)
            raise LLMError(
                "CLAUDE_CODE_TIMEOUT",
                f"claude CLI timed out after {int(_TIMEOUT_SECONDS)}s",
                self._provider,
            ) from exc
        except asyncio.CancelledError:
            # 客户端断连/上游取消：必须杀掉整组，否则 CLI 会把这轮跑完、白烧订阅额度
            await self._kill_process_group(proc)
            raise
        if proc.returncode != 0:
            detail = (stderr or stdout or b"").decode("utf-8", "replace")[-500:]
            raise LLMError("CLAUDE_CODE_ERROR", f"exit {proc.returncode}: {detail}", self._provider)
        return parse_result(stdout.decode("utf-8", "replace"), self._provider)

    async def _run(self, request: LLMRequest) -> LLMResponse:
        async with self._semaphore:
            proc = await self._spawn(request)
            try:
                return await self._communicate(proc, request)
            finally:
                await self._kill_process_group(proc)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started_at = log_llm_request_start(
            logger, model=request.model, provider=self._provider, request_type="complete"
        )
        try:
            response = await self._run(request)
        except asyncio.CancelledError:
            raise
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
            ensure_home_config(self._home, logger)
            proc = await asyncio.create_subprocess_exec(
                self._command, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd, env=build_env(self._home),
            )
            await asyncio.wait_for(proc.communicate(), timeout=30.0)
            return proc.returncode == 0
        except LLMError:
            raise
        except Exception as exc:
            logger.warning("claude_code_test_connection_failed", error=str(exc))
            return False


__all__ = ["ClaudeCodeAdapter"]
