from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SPEC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AgentCategory(StrEnum):
    CODING = "coding"
    CHAT = "chat"
    RESEARCH = "research"
    AGGREGATION = "aggregation"
    DOCUMENT = "document"
    ASSISTANT = "assistant"


class SubAgentPolicy(BaseModel):
    # 白名单语义：空列表 = 不限制；配置了条目才收紧（allowed_specs/
    # allowed_inline_templates/allowed_inline_tools 同此约定）。
    allowed_specs: list[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1)
    max_depth: int = Field(default=1, ge=0)
    allow_inline_roles: bool = True
    allowed_inline_templates: list[str] = Field(default_factory=list)
    allowed_inline_tools: list[str] = Field(default_factory=list)
    max_iterations_default: int = Field(default=20, ge=1)
    max_iterations_cap: int = Field(default=60, ge=1)
    role_name_max_length: int = Field(default=80, ge=1)
    reuse_ttl_seconds: int = Field(default=86400, ge=0)
    enable_final_review: bool = True
    final_review_counts_toward_capacity: bool = False
    enable_legacy_tools: bool = True


class ToolConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed_tools: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    tool_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        alias="tool_config",
    )

    @model_validator(mode="after")
    def include_history_lookup(self) -> ToolConfig:
        if self.allowed_tools and "read_history" not in self.allowed_tools:
            self.allowed_tools = [*self.allowed_tools, "read_history"]
        return self


class AgentSpec(BaseModel):
    id: str
    title: str
    category: AgentCategory
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    provider: str = ""
    max_iterations: int = Field(default=20, ge=1)
    timeout_seconds: float = Field(default=300.0, ge=10.0)
    default_mode: str = "direct"
    allow_modes: list[str] = Field(default_factory=lambda: ["direct", "plan_execute"])
    enabled: bool = True
    tools: ToolConfig = Field(default_factory=ToolConfig)
    sub_agents: SubAgentPolicy = Field(default_factory=SubAgentPolicy)
    source_path: str = ""
    mode: Literal["inject", "loop"] = "loop"
    trigger_keywords: list[str] = Field(default_factory=list)
    inject_max_chars: int = Field(default=2000, ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _SPEC_ID_PATTERN.fullmatch(value):
            raise ValueError("id must match [A-Za-z0-9_-]{1,64}")
        return value

    @model_validator(mode="after")
    def validate_modes(self) -> AgentSpec:
        if self.default_mode not in self.allow_modes:
            raise ValueError(
                f"default_mode {self.default_mode!r} must be in allow_modes {self.allow_modes}"
            )
        return self


__all__ = [
    "AgentCategory",
    "AgentSpec",
    "SubAgentPolicy",
    "ToolConfig",
]
