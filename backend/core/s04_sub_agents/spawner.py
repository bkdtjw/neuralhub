from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import AgentConfig, AgentEventHandler, ToolResult
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry
from backend.core.system_prompt import build_system_prompt

from .agent_definition import AgentDefinitionLoader, AgentRole
from .progress import SubAgentProgressEmitter


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
        progress_handler: AgentEventHandler | None = None,
    ) -> None:
        self._adapter = adapter
        self._parent_registry = parent_registry
        self._definition_loader = definition_loader
        self._default_model = default_model
        self._progress_handler = progress_handler

    async def spawn_and_run(self, params: SpawnParams) -> ToolResult:
        loop: AgentLoop | None = None
        progress = SubAgentProgressEmitter(self._progress_handler, "dispatch")
        label = params.role or "sub-agent"
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
            loop.on(progress.child_observer(label))
            await progress.spawned(total=1, specs=[label], message=f"派发子 agent {label} 处理子任务…")
            result = await loop.run(params.task)
            await progress.agent_done(
                role=label, completed=1, total=1, message=f"子 agent {label} 已完成（1/1）"
            )
            return ToolResult(output=result.content.strip())
        except asyncio.CancelledError:
            if loop is not None:
                loop.abort()
            raise
        except AgentError as exc:
            await progress.agent_done(
                role=label, completed=1, total=1, error=exc.message,
                message=f"子 agent {label} 执行失败：{exc.message}",
            )
            raise
        except Exception as exc:
            await progress.agent_done(
                role=label, completed=1, total=1, error=str(exc),
                message=f"子 agent {label} 执行失败：{exc}",
            )
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
