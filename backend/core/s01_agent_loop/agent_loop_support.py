from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from backend.common.logging import bound_log_context, get_log_context, get_logger, new_trace_id
from backend.common.message_history import sanitize_message_history
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from backend.core.s06_context_compression.summary_helpers import is_summary_message
from backend.core.system_prompt import build_runtime_context

# patch_orphan_tool_calls 已抽到 agent_loop_orphan，此处显式再导出保持既有导入路径不变。
from .agent_loop_orphan import patch_orphan_tool_calls as patch_orphan_tool_calls


def _cache_key_part(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())[:40]
    return normalized or "default"


@dataclass(frozen=True)
class PromptCachePrefix:
    provider: str
    model: str
    system_prompt: str
    tools: list[ToolDefinition]


def build_prompt_cache_key(prefix: PromptCachePrefix) -> str:
    digest = build_cache_prefix_hash(prefix.system_prompt, prefix.tools)[:16]
    return f"agent-studio:{_cache_key_part(prefix.provider)}:{_cache_key_part(prefix.model)}:{digest}"  # noqa: E501


def build_cache_prefix_hash(system_prompt: str, tools: list[ToolDefinition]) -> str:
    payload = {
        "system_prompt": system_prompt,
        "tools": [tool.model_dump(mode="json") for tool in tools],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_llm_request(
    config: AgentConfig,
    messages: list[Message],
    tools: list[ToolDefinition],
    *,
    skill_loader: Any | None = None,
    memory_index: Any | None = None,
    static_skill_messages: list[Message] | None = None,
) -> LLMRequest:
    system_msg, summary, recent = _split_history(messages)
    # 自愈：丢弃已污染会话里的孤儿 tool 消息，避免每轮发送都触发 LLM 400（不改内存历史本体）。
    recent = sanitize_message_history(recent)
    system_prompt = config.system_prompt or (system_msg.content if system_msg else "")
    latest_text = _latest_user_text(recent)
    skill_messages = [
        *_coerce_zone_messages(static_skill_messages or []),
        *_coerce_zone_messages(skill_loader.match(latest_text) if skill_loader else []),
    ]
    skill_messages = [
        message
        for message in skill_messages
        if not (message.role == "system" and message.content == system_prompt)
    ]
    memory_messages = _coerce_zone_messages(
        memory_index.match(latest_text, limit=5) if memory_index else []
    )
    runtime_messages = _runtime_messages(config.workspace, tools)
    prefix_hash = build_cache_prefix_hash(system_prompt, tools)
    legacy_system = system_msg or (Message(role="system", content=system_prompt) if system_prompt else None)  # noqa: E501
    legacy_messages = [
        *([legacy_system] if legacy_system else []),
        *skill_messages,
        *memory_messages,
        *runtime_messages,
        *([summary] if summary else []),
        *recent,
    ]
    return LLMRequest(
        model=config.model,
        system_prompt=system_prompt,
        tools=tools or None,
        skill_messages=skill_messages,
        memory_messages=memory_messages,
        runtime_messages=runtime_messages,
        summary_message=summary,
        recent_messages=recent,
        cache_prefix_hash=prefix_hash,
        messages=legacy_messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        thinking=config.thinking_enabled,
        prompt_cache_key=build_prompt_cache_key(
            PromptCachePrefix(config.provider, config.model, system_prompt, tools)
        ),
    )


def _split_history(messages: list[Message]) -> tuple[Message | None, Message | None, list[Message]]:
    system_msg = next((message for message in messages if message.role == "system"), None)
    non_system = [message for message in messages if message.role != "system"]
    summaries = [message for message in non_system if is_summary_message(message)]
    summary = _combine_summaries(summaries)
    recent = [message for message in non_system if not is_summary_message(message)]
    return system_msg, summary, recent


def _combine_summaries(messages: list[Message]) -> Message | None:
    if not messages:
        return None
    content = "\n\n".join(message.content.strip() for message in messages if message.content.strip())
    return Message(role="user", kind="summary", content=content)


def _latest_user_text(messages: list[Message]) -> str:
    return next(
        (
            message.content
            for message in reversed(messages)
            if message.role == "user"
            and message.kind == "user_request"
            and not message.ephemeral
        ),
        "",
    )


def _coerce_zone_messages(items: Any) -> list[Message]:
    result: list[Message] = []
    for item in items or []:
        if isinstance(item, Message):
            result.append(item)
        elif hasattr(item, "lesson"):
            result.append(_memory_entry_to_message(item))
        elif isinstance(item, str) and item.strip():
            result.append(_skill_text_message(item.strip()))
    return result


def _memory_entry_to_message(entry: Any) -> Message:
    trigger = str(getattr(entry, "trigger", "")).strip()
    lesson = str(getattr(entry, "lesson", "")).strip()
    content = f"[长期记忆]\n触发: {trigger}\n经验: {lesson}".strip()
    return Message(
        role="user",
        kind="memory_context",
        content=f"<memory_context>\n{content}\n</memory_context>",
    )


def _skill_text_message(content: str) -> Message:
    return Message(
        role="user",
        kind="skill_context",
        content=f"<skill_context>\n{content}\n</skill_context>",
    )


def _runtime_messages(workspace: str, tools: list[ToolDefinition]) -> list[Message]:
    content = build_runtime_context(workspace, tools).strip()
    if not content:
        return []
    return [
        Message(
            role="user",
            kind="runtime_context",
            content=f"<runtime_context>\n{content}\n</runtime_context>",
        )
    ]


def response_content(response: LLMResponse) -> str:
    content = response.content or ""
    if content.strip() or response.tool_calls:
        return content
    return response.provider_metadata.get("reasoning_content", "") or ""


def message_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def build_run_logger(session_id: str) -> tuple[str, str, Any, Any]:
    context = get_log_context()
    trace_id = str(context.get("trace_id") or new_trace_id())
    effective_session_id = session_id or str(context.get("session_id") or "")
    return (
        trace_id,
        effective_session_id,
        get_logger(
            component="agent_loop",
            trace_id=trace_id,
            session_id=effective_session_id,
        ),
        bound_log_context(
            trace_id=trace_id,
            session_id=effective_session_id,
        ),
    )


def log_llm_call_end(logger: Any, response: LLMResponse) -> None:
    logger.info(
        "llm_call_end",
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        cached_prompt_tokens=response.usage.cached_prompt_tokens,
        total_tokens=response.usage.prompt_tokens + response.usage.completion_tokens,
    )


def log_tool_result(logger: Any, tool_call: ToolCall | None, result: ToolResult) -> None:
    logger.info(
        "tool_call_end",
        tool=tool_call.name if tool_call is not None else "",
        tool_call_id=result.tool_call_id,
        is_error=result.is_error,
    )
