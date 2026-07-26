from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.common import LLMError
from backend.common.types import LLMRequest, LLMResponse, LLMUsage, Message

from .message_zones import request_system_prompt, request_zone_messages

# 内建工具集直接清空（--tools ""）：本 provider 只当纯文本 LLM 用。
# 实测这一项把 CLI 自带前缀从约 2 万 token 降到 170 token——比缓存它更划算。
# --disallowedTools 仍保留为纵深防御：它是权限拒绝表，不影响工具是否进上下文。
_TOOLS_DISABLED = ""
_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task,Agent,"
    "TodoWrite,Skill,SlashCommand,KillShell,BashOutput,EnterPlanMode,ExitPlanMode"
)
# 进程环境可能带指向其它厂商 compat 端点的 ANTHROPIC_* 覆写（app 容器就配了 zhipu），
# CLI 会优先吃它们导致模型不存在/鉴权错乱；剥掉，强制走订阅登录态。
_STRIPPED_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    }
)


def render_message(message: Message) -> str:
    parts: list[str] = []
    text = (message.content or "").strip()
    if text:
        parts.append(f"[{message.role}] {text}")
    for call in message.tool_calls or []:
        parts.append(
            f"[{message.role} 调用工具 {call.name}] {json.dumps(call.arguments, ensure_ascii=False)}"
        )
    for result in message.tool_results or []:
        parts.append(f"[工具结果] {result.output}")
    return "\n".join(parts)


def render_prompt(request: LLMRequest) -> str:
    rendered = [render_message(m) for m in request_zone_messages(request, include_system=False)]
    body = "\n\n".join(part for part in rendered if part)
    return f"{body}\n\n请以 assistant 身份直接回复最后一条 user 消息。"


def parse_result(raw: str, provider: str) -> LLMResponse:
    try:
        data: dict[str, Any] = json.loads(raw)
    except ValueError as exc:
        raise LLMError(
            "CLAUDE_CODE_PARSE_ERROR", f"invalid JSON from CLI: {raw[:200]}", provider
        ) from exc
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


def build_env(home: str) -> dict[str, str]:
    env = dict(os.environ)
    if home:
        env["HOME"] = home
    return {key: value for key, value in env.items() if key not in _STRIPPED_ENV_KEYS}


def ensure_home_config(home: str, logger: Any) -> None:
    """CLI 要求 $HOME/.claude.json 存在（容器内首跑没有且因 backups 存在而拒绝自建），补种最小配置。"""
    if not home:
        return
    path = Path(home) / ".claude.json"
    try:
        if not path.exists():
            path.write_text('{"hasCompletedOnboarding": true}', encoding="utf-8")
    except OSError:
        logger.warning("claude_code_home_seed_failed", path=str(path))


def build_args(command: str, request: LLMRequest, default_model: str) -> list[str]:
    args = [
        command,
        "-p",
        "--output-format",
        "json",
        "--model",
        request.model or default_model,
        "--tools",
        _TOOLS_DISABLED,
        "--disallowedTools",
        _DISALLOWED_TOOLS,
        # 单发调用不需要会话续跑，避免每次往挂载的 home 落无用 transcript
        "--no-session-persistence",
    ]
    system_prompt = request_system_prompt(request)
    if system_prompt:
        args.extend(["--system-prompt", system_prompt])
    return args


__all__ = [
    "build_args",
    "build_env",
    "ensure_home_config",
    "parse_result",
    "render_message",
    "render_prompt",
]
