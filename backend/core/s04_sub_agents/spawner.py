from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import AgentConfig, ToolResult
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry
from backend.core.system_prompt import build_system_prompt

from .agent_definition import AgentDefinitionLoader, AgentRole


class SpawnParams(BaseModel):
    """Parameters for the dispatch_agent tool."""

    role: str = ""
    task: str
    context: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    model: str = ""


class SubAgentSpawner:
    """Create and run child AgentLoop instances."""

    def __init__(
        self,
        adapter: LLMAdapter,
        parent_registry: ToolRegistry,
        definition_loader: AgentDefinitionLoader,
        default_model: str,
    ) -> None:
        self._adapter = adapter
        self._parent_registry = parent_registry
        self._definition_loader = definition_loader
        self._default_model = default_model

    async def spawn_and_run(self, params: SpawnParams) -> ToolResult:
        loop: AgentLoop | None = None
        try:
            role = self._load_role(params.role)
            child_registry = self._build_child_registry(
                self._parent_registry,
                params.allowed_tools or (role.allowed_tools if role is not None else []),
            )
            loop = AgentLoop(
                config=AgentConfig(
                    model=params.model or (role.model if role is not None else "") or self._default_model,
                    system_prompt=self._build_system_prompt(role, params),
                    max_iterations=role.max_iterations if role is not None else 10,
                ),
                adapter=self._adapter,
                tool_registry=child_registry,
            )
            result = await loop.run(params.task)
            return ToolResult(output=result.content.strip())
        except asyncio.CancelledError:
            if loop is not None:
                loop.abort()
            raise
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SUB_AGENT_SPAWN_ERROR", str(exc)) from exc

    def _build_child_registry(self, parent_registry: ToolRegistry, allowed_tools: list[str]) -> ToolRegistry:
        child_registry = ToolRegistry()
        allowed = set(allowed_tools)
        for definition in parent_registry.list_definitions():
            if definition.name in {"dispatch_agent", "orchestrate_agents"}:
                continue
            if allowed and definition.name not in allowed:
                continue
            registered = parent_registry.get(definition.name)
            if registered is None:
                continue
            _, executor = registered
            child_registry.register(definition, executor)
        return child_registry

    def _build_system_prompt(self, role: AgentRole | None, params: SpawnParams) -> str:
        parts = [build_system_prompt()]
        if role is not None:
            parts.append(f"你的角色是 {role.name}。{role.description}")
            parts.append(role.system_prompt)
        else:
            if params.role:
                parts.append(f"你的角色是 {params.role}。请根据角色名称理解自己的职责，专注完成分配的子任务。")
            else:
                parts.append("你是一个被派生出来处理子任务的专用 Agent，请只聚焦当前任务。")
        if params.context:
            parts.append(f"额外上下文:\n{params.context}")
        parts.append("请直接完成子任务，并输出简洁、可复用的结果。")
        return "\n\n".join(part.strip() for part in parts if part.strip())

    def _load_role(self, role_name: str) -> AgentRole | None:
        if not role_name:
            return None
        return self._definition_loader.load_role(role_name)


__all__ = ["SpawnParams", "SubAgentSpawner"]
