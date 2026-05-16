from __future__ import annotations

import os
import re

from pydantic import BaseModel, ConfigDict

from backend.adapters.base import LLMAdapter
from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.common.types import AgentConfig, AgentEventHandler, ProviderConfig
from backend.config.settings import Settings
from backend.core.s01_agent_loop import AgentLoop, CheckpointFn, PlanExecuteRunner, PlanRenderer
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPServerManager, MCPToolBridge
from backend.core.system_prompt import build_system_prompt
from backend.core.task_queue import TaskQueue

from .mcp_requirements import extract_required_mcp_servers
from .models import AgentCategory, AgentSpec, ToolConfig
from .registry import SpecRegistry
from .runtime_plan import create_runtime_runner
from .runtime_support import FilteredBridge, build_runtime_registry


class AgentRuntimeDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    provider_manager: ProviderManager
    mcp_manager: MCPServerManager
    settings: Settings
    spec_registry: SpecRegistry


class AgentRuntime:
    def __init__(self, deps: AgentRuntimeDeps) -> None:
        self._deps = deps

    async def create_loop(
        self,
        spec: AgentSpec,
        workspace: str = "",
        session_id: str = "",
        model: str = "",
        provider: str = "",
        task_queue: TaskQueue | None = None,
        event_handler: AgentEventHandler | None = None,
        is_sub_agent: bool = False,
        checkpoint_fn: CheckpointFn | None = None,
    ) -> AgentLoop:
        try:
            resolved_provider = await self._resolve_provider(provider or spec.provider)
            resolved_model = model or spec.model or resolved_provider.default_model
            resolved_model = resolved_model or self._deps.settings.default_model
            resolved_workspace = os.path.abspath(workspace or os.getcwd())
            adapter = await self._deps.provider_manager.get_adapter(resolved_provider.id)
            registry = self._build_registry(
                spec.tools,
                spec.sub_agents.max_depth,
                resolved_workspace,
                adapter,
                resolved_model,
                session_id,
                task_queue,
                event_handler,
                is_sub_agent,
            )
            bridge = FilteredBridge(
                MCPToolBridge(self._deps.mcp_manager, registry),
                registry,
                set(spec.tools.allowed_tools),
                extract_required_mcp_servers(spec),
            )
            await bridge.sync_all()
            loop = AgentLoop(
                config=AgentConfig(
                    model=resolved_model,
                    provider=resolved_provider.id,
                    system_prompt=self._compose_system_prompt(
                        resolved_workspace, spec.system_prompt
                    ),
                    session_id=session_id,
                    tools=sorted(tool.name for tool in registry.list_definitions()),
                    max_iterations=spec.max_iterations,
                    timeout_seconds=spec.timeout_seconds,
                ),
                adapter=adapter,
                tool_registry=registry,
                checkpoint_fn=checkpoint_fn,
                bridge=bridge,
                agent_spec=spec,
                owner_id=session_id,
            )
            return loop
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SKILL_RUNTIME_CREATE_LOOP_ERROR", str(exc)) from exc

    async def create_loop_from_id(
        self,
        spec_id: str,
        workspace: str = "",
        session_id: str = "",
        model: str = "",
        provider: str = "",
        task_queue: TaskQueue | None = None,
        event_handler: AgentEventHandler | None = None,
        is_sub_agent: bool = False,
        checkpoint_fn: CheckpointFn | None = None,
    ) -> AgentLoop:
        try:
            spec = self._deps.spec_registry.get(spec_id)
            if spec is None:
                raise AgentError("SKILL_SPEC_NOT_FOUND", f"Skill spec not found: {spec_id}")
            if not spec.enabled:
                raise AgentError("SKILL_SPEC_DISABLED", f"Skill spec is disabled: {spec_id}")
            return await self.create_loop(
                spec,
                workspace=workspace,
                session_id=session_id,
                model=model,
                provider=provider,
                task_queue=task_queue,
                event_handler=event_handler,
                is_sub_agent=is_sub_agent,
                checkpoint_fn=checkpoint_fn,
            )
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SKILL_RUNTIME_CREATE_FROM_ID_ERROR", str(exc)) from exc

    async def create_loop_inline(
        self,
        role: str,
        system_prompt: str,
        tools: list[str],
        model: str = "",
        workspace: str = "",
        task_queue: TaskQueue | None = None,
        event_handler: AgentEventHandler | None = None,
        is_sub_agent: bool = False,
        session_id: str = "",
        checkpoint_fn: CheckpointFn | None = None,
    ) -> AgentLoop:
        try:
            slug = re.sub(r"[^A-Za-z0-9_-]+", "-", role or "inline-agent")
            slug = slug.strip("-_") or "inline-agent"
            spec = AgentSpec(
                id=f"inline_{slug}"[:64],
                title=role or "Inline Agent",
                category=AgentCategory.ASSISTANT,
                description=role,
                system_prompt=system_prompt,
                model=model,
                tools=ToolConfig(allowed_tools=tools),
                source_path="inline",
            )
            return await self.create_loop(
                spec,
                workspace=workspace,
                session_id=session_id,
                task_queue=task_queue,
                event_handler=event_handler,
                is_sub_agent=is_sub_agent,
                checkpoint_fn=checkpoint_fn,
            )
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SKILL_RUNTIME_CREATE_INLINE_ERROR", str(exc)) from exc

    async def create_runner(
        self,
        spec: AgentSpec | None = None,
        spec_id: str = "",
        mode: str = "",
        workspace: str = "",
        session_id: str = "",
        model: str = "",
        provider: str = "",
        task_queue: TaskQueue | None = None,
        event_handler: AgentEventHandler | None = None,
        renderer: PlanRenderer | None = None,
        is_sub_agent: bool = False,
        checkpoint_fn: CheckpointFn | None = None,
        owner_id: str = "unknown",
    ) -> AgentLoop | PlanExecuteRunner:
        return await create_runtime_runner(
            self,
            spec,
            spec_id,
            mode,
            workspace,
            session_id,
            model,
            provider,
            task_queue,
            event_handler,
            renderer,
            is_sub_agent,
            checkpoint_fn,
            owner_id,
            MCPToolBridge,
        )

    def _build_registry(
        self,
        tools: ToolConfig,
        max_depth: int,
        workspace: str,
        adapter: LLMAdapter,
        model: str,
        session_id: str,
        task_queue: TaskQueue | None,
        event_handler: AgentEventHandler | None,
        is_sub_agent: bool,
    ) -> ToolRegistry:
        return build_runtime_registry(
            register_builtin_tools,
            tools,
            max_depth,
            workspace,
            adapter,
            model,
            session_id,
            task_queue,
            event_handler,
            self,
            self._deps.spec_registry,
            is_sub_agent,
        )

    async def _resolve_provider(self, requested: str) -> ProviderConfig:
        providers = await self._deps.provider_manager.list_all()
        if not providers:
            raise AgentError("SKILL_PROVIDER_MISSING", "No provider configured")
        if requested:
            for provider in providers:
                if provider.id == requested or provider.provider_type.value == requested:
                    return provider
            raise AgentError("SKILL_PROVIDER_NOT_FOUND", f"Provider not found: {requested}")
        default_provider = await self._deps.provider_manager.get_default()
        return default_provider or providers[0]

    @staticmethod
    def _compose_system_prompt(workspace: str, spec_prompt: str) -> str:
        return "\n\n".join(
            part for part in [build_system_prompt(workspace), spec_prompt.strip()] if part
        )


__all__ = ["AgentRuntime", "AgentRuntimeDeps"]
