from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Role = Literal["user", "assistant", "system", "tool"]
MessageKind = Literal[
    "user_request",
    "summary",
    "runtime_guard",
    "runtime_context",
    "skill_context",
    "memory_context",
]


def generate_id() -> str:
    # 全 32 位 uuid4 hex（122 bit 随机），避免 messages.id 全局主键长期生日碰撞。
    return uuid4().hex


class ToolCall(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    arguments: dict[str, Any]


class FileDiff(BaseModel):
    path: str
    unified_diff: str
    change_type: Literal["create", "modify", "delete"] = "modify"


class ToolArtifact(BaseModel):
    kind: Literal["image", "file"] = "file"
    path: str
    mime_type: str = ""
    label: str = ""
    source: str = ""
    temporary: bool = False


class ToolResult(BaseModel):
    tool_call_id: str = Field(default_factory=generate_id)
    output: str
    is_error: bool = False
    diffs: list[FileDiff] = Field(default_factory=list)
    artifacts: list[ToolArtifact] = Field(default_factory=list)


class Message(BaseModel):
    id: str = Field(default_factory=generate_id)
    role: Role
    content: str
    kind: MessageKind = "user_request"
    ephemeral: bool = False
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class StreamChunk(BaseModel):
    # "usage" carries {prompt_tokens, completion_tokens, cached_prompt_tokens,
    # cache_creation_prompt_tokens}; emitted mid-stream so streaming responses
    # can report token usage.
    type: Literal["text", "reasoning", "tool_call", "tool_result", "done", "usage"]
    data: Any = None


def merge_usage(acc: dict[str, Any], data: Any) -> None:
    """Fold a usage StreamChunk payload into ``acc`` in place.

    Uses last-non-zero-per-field semantics (never sums): Anthropic reports
    prompt/cached tokens on ``message_start`` and completion tokens on
    ``message_delta`` as two separate usage chunks, so summing would double
    count while plain last-write-wins would let the completion chunk's zeroed
    prompt field wipe out the real prompt count.
    """
    if not isinstance(data, dict):
        return
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "cache_creation_prompt_tokens",
    ):
        value = data.get(key)
        if value:
            acc[key] = int(value)


__all__ = [
    "Role",
    "MessageKind",
    "FileDiff",
    "ToolArtifact",
    "ToolCall",
    "ToolResult",
    "Message",
    "StreamChunk",
    "merge_usage",
    "generate_id",
]
