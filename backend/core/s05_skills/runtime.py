from __future__ import annotations

import os
import re

from pydantic import BaseModel, ConfigDict

from backend.adapters.base import LLMAdapter
from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import AgentConfig, AgentEventHandler, Message, ProviderConfig
from backend.config.settings import Settings
from backend.core.s01_agent_loop import AgentLoop, CheckpointFn, PlanExecuteRunner, PlanRenderer
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPServerManager, MCPToolBridge
from backend.core.s06_context_compression import LongTermMemory, MemoryIndex
from backend.core.system_prompt import build_system_prompt
from backend.core.task_queue import TaskQueue
from backend.storage.memory_store import MemoryStore

from .mcp_requirements import extract_required_mcp_servers
from .models import AgentCategory, AgentSpec, ToolConfig
from .on_demand_loader import OnDemandSkillLoader
from .registry import SpecRegistry
from .runtime_plan import create_runtime_runner
from .runtime_support import (
    FilteredBridge,
    allowed_tools_with_defaults,
    build_runtime_registry,
)

logger = get_logger(component="agent_runtime")


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
        max_tokens: int = 16384,
        temperature: float = 0.7,
    ) -> AgentLoop:
        try:
            resolved_provider = await self._resolve_provider(provider or spec.provider)
            resolved_model = model or spec.model or resolved_provider.default_model
            resolved_model = resolved_model or self._deps.settings.default_model
            resolved_workspace = os.path.abspath(workspace or os.getcwd())
            adapter = await self._deps.provider_manager.get_adapter(resolved_provider.id)
            skill_loader = OnDemandSkillLoader(self._deps.spec_registry)
            memory_index = self._build_memory_index()
            stable_prompt, skill_prompt = self._compose_layered_prompt(
                resolved_workspace,
                spec.system_prompt,
            )
            registry = self._build_registry(
                spec.tools,
                spec.sub_agents.max_depth,
                resolved_workspace,
                adapter,
                resolved_model,
                resolved_provider.id,
                session_id,
                task_queue,
                event_handler,
                is_sub_agent,
                skill_loader,
                sub_agent_policy=spec.sub_agents,
            )
            bridge = FilteredBridge(
                MCPToolBridge(self._deps.mcp_manager, registry),
                registry,
                allowed_tools_with_defaults(spec.tools),
                extract_required_mcp_servers(spec),
            )
            await bridge.sync_all()
            loop = AgentLoop(
                config=AgentConfig(
                    model=resolved_model,
                    provider=resolved_provider.id,
                    system_prompt=stable_prompt,
                    workspace=resolved_workspace,
                    session_id=session_id,
                    tools=sorted(tool.name for tool in registry.list_definitions()),
                    max_iterations=spec.max_iterations,
                    timeout_seconds=spec.timeout_seconds,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                adapter=adapter,
                tool_registry=registry,
                checkpoint_fn=checkpoint_fn,
                bridge=bridge,
                agent_spec=spec,
                owner_id=session_id,
                skill_loader=skill_loader,
                memory_index=memory_index,
                static_skill_messages=_skill_messages(skill_prompt),
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
        max_tokens: int = 16384,
        temperature: float = 0.7,
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
                max_tokens=max_tokens,
                temperature=temperature,
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
        provider: str = "",
        workspace: str = "",
        task_queue: TaskQueue | None = None,
        event_handler: AgentEventHandler | None = None,
        is_sub_agent: bool = False,
        session_id: str = "",
        checkpoint_fn: CheckpointFn | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.7,
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
                model=model,
                provider=provider,
                task_queue=task_queue,
                event_handler=event_handler,
                is_sub_agent=is_sub_agent,
                checkpoint_fn=checkpoint_fn,
                max_tokens=max_tokens,
                temperature=temperature,
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
        provider: str,
        session_id: str,
        task_queue: TaskQueue | None,
        event_handler: AgentEventHandler | None,
        is_sub_agent: bool,
        skill_loader: OnDemandSkillLoader | None = None,
        sub_agent_policy: object | None = None,
    ) -> ToolRegistry:
        return build_runtime_registry(
            register_builtin_tools,
            tools,
            max_depth,
            workspace,
            adapter,
            model,
            provider,
            session_id,
            task_queue,
            event_handler,
            self,
            self._deps.spec_registry,
            is_sub_agent,
            skill_loader,
            zhipu_web_search_api_key=self._deps.settings.zhipu_web_search_api_key,
            sub_agent_policy=sub_agent_policy,
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
    def _compose_layered_prompt(workspace: str, spec_prompt: str) -> tuple[str, str]:
        return build_system_prompt(), spec_prompt.strip()

    @staticmethod
    def _compose_system_prompt(workspace: str, spec_prompt: str) -> str:
        stable, dynamic = AgentRuntime._compose_layered_prompt(workspace, spec_prompt)
        return "\n\n".join(part for part in [stable, dynamic] if part)

    @staticmethod
    def _build_memory_index() -> MemoryIndex:
        try:
            return MemoryIndex(MemoryStore().load())
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_index_build_degraded", error=str(exc))
            return MemoryIndex(LongTermMemory())


__all__ = ["AgentRuntime", "AgentRuntimeDeps"]


def _skill_messages(prompt: str) -> list[Message]:
    if not prompt:
        return []
    return [
        Message(
            role="user",
            kind="skill_context",
            content=f"<skill_context>\n{prompt}\n</skill_context>",
        )
    ]
