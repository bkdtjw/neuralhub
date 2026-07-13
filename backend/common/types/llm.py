from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .message import Message, ToolCall, generate_id
from .tool import ToolDefinition


class ProviderType(str, Enum):  # noqa: UP042
    OPENAI_COMPAT = "openai_compat"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class ProviderConfig(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    provider_type: ProviderType
    base_url: str
    api_key: str = ""
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    is_default: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)
    enable_prompt_cache: bool = False
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    roles: str = ""


class LLMRequest(BaseModel):
    model: str
    system_prompt: str = ""
    tools: list[ToolDefinition] | None = None
    skill_messages: list[Message] = Field(default_factory=list)
    memory_messages: list[Message] = Field(default_factory=list)
    runtime_messages: list[Message] = Field(default_factory=list)
    summary_message: Message | None = None
    recent_messages: list[Message] = Field(default_factory=list)
    cache_prefix_hash: str = ""
    messages: list[Message] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    temperature: float = 0.7
    max_tokens: int = 16384
    thinking: bool = False
    prompt_cache_key: str = ""
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None


class LLMUsage(BaseModel):
    # prompt_tokens 统一为"未走缓存的输入"：Anthropic 的 input_tokens 天然不含
    # cache_read/cache_creation；OpenAI 的 prompt_tokens 含 cached_tokens，解析时扣除。
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_creation_prompt_tokens: int = 0


class LLMResponse(BaseModel):
    id: str = Field(default_factory=generate_id)
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ProviderType",
    "ProviderConfig",
    "LLMRequest",
    "LLMUsage",
    "LLMResponse",
]
