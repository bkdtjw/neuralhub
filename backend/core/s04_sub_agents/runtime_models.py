from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.base import LLMAdapter
from backend.common.types import AgentTask, PermissionLevel
from backend.core.s02_tools import ToolRegistry


class OrchestratorConfig(BaseModel):
    workspace: str
    default_model: str
    timeout_per_agent: float = 120.0
    agents_dir: str | None = None
    max_parallel_agents: int = 5


class IsolatedRegistryConfig(BaseModel):
    permission_level: PermissionLevel
    allowed_tool_names: list[str] = Field(default_factory=list)
    workspace: str


class IsolatedAgentRun(BaseModel):
    task: AgentTask
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    max_iterations: int = 10
    dependency_outputs: dict[str, str] = Field(default_factory=dict)


class IsolatedAgentRuntime(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    adapter: LLMAdapter
    parent_registry: ToolRegistry
    config: OrchestratorConfig


__all__ = [
    "IsolatedAgentRun",
    "IsolatedAgentRuntime",
    "IsolatedRegistryConfig",
    "OrchestratorConfig",
]
