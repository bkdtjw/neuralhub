from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.common.errors import AgentError
from backend.common.types import AgentEventHandler
from backend.core.s01_agent_loop import (
    AgentLoop,
    CheckpointFn,
    PlanExecuteRunner,
    PlanRenderer,
    PlanStore,
    SilentPlanRenderer,
    TodoStore,
)
from backend.core.s02_tools.mcp import MCPToolBridge
from backend.core.task_queue import TaskQueue

from .mcp_requirements import extract_required_mcp_servers
from .models import AgentCategory, AgentSpec, ToolConfig
from .runtime_support import FilteredBridge

if TYPE_CHECKING:
    from .runtime import AgentRuntime

_DIRECT_MODE = "direct"
_PLAN_MODE = "plan_execute"


async def create_runtime_runner(
    runtime: AgentRuntime,
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
    bridge_cls: type[MCPToolBridge] = MCPToolBridge,
) -> AgentLoop | PlanExecuteRunner:
    resolved_spec = _resolve_spec(runtime, spec, spec_id)
    effective_mode = _effective_mode(resolved_spec, mode)
    _validate_mode(resolved_spec, effective_mode)
    if effective_mode == _DIRECT_MODE:
        return await _create_direct_runner(
            runtime,
            resolved_spec,
            workspace,
            session_id,
            model,
            provider,
            task_queue,
            event_handler,
            is_sub_agent,
            checkpoint_fn,
        )
    if effective_mode == _PLAN_MODE:
        return await _create_plan_runner(
            runtime,
            resolved_spec,
            workspace,
            session_id,
            model,
            provider,
            task_queue,
            event_handler,
            renderer,
            is_sub_agent,
            owner_id,
            bridge_cls,
        )
    raise AgentError("MODE_NOT_SUPPORTED", f"Unsupported runner mode: {effective_mode}")


def _resolve_spec(runtime: AgentRuntime, spec: AgentSpec | None, spec_id: str) -> AgentSpec | None:
    if spec is not None or not spec_id:
        return spec
    resolved = runtime._deps.spec_registry.get(spec_id)  # noqa: SLF001
    if resolved is None:
        raise AgentError("SKILL_SPEC_NOT_FOUND", f"Skill spec not found: {spec_id}")
    if not resolved.enabled:
        raise AgentError("SKILL_SPEC_DISABLED", f"Skill spec is disabled: {spec_id}")
    return resolved


def _effective_mode(spec: AgentSpec | None, mode: str) -> str:
    return (mode or (spec.default_mode if spec is not None else "") or _DIRECT_MODE).strip()


def _validate_mode(spec: AgentSpec | None, mode: str) -> None:
    if spec is not None and mode not in spec.allow_modes:
        raise AgentError("MODE_NOT_ALLOWED", f"Mode {mode!r} is not allowed for skill {spec.id}")


async def _create_direct_runner(
    runtime: AgentRuntime,
    spec: AgentSpec | None,
    workspace: str,
    session_id: str,
    model: str,
    provider: str,
    task_queue: TaskQueue | None,
    event_handler: AgentEventHandler | None,
    is_sub_agent: bool,
    checkpoint_fn: CheckpointFn | None,
) -> AgentLoop:
    resolved = spec or AgentSpec(
        id="inline-runner",
        title="Inline Runner",
        category=AgentCategory.ASSISTANT,
        tools=ToolConfig(),
        source_path="inline",
    )
    return await runtime.create_loop(
        resolved,
        workspace,
        session_id,
        model,
        provider,
        task_queue,
        event_handler,
        is_sub_agent,
        checkpoint_fn,
    )


async def _create_plan_runner(
    runtime: AgentRuntime,
    spec: AgentSpec | None,
    workspace: str,
    session_id: str,
    model: str,
    provider: str,
    task_queue: TaskQueue | None,
    event_handler: AgentEventHandler | None,
    renderer: PlanRenderer | None,
    is_sub_agent: bool,
    owner_id: str,
    bridge_cls: type[MCPToolBridge],
) -> PlanExecuteRunner:
    resolved_workspace = os.path.abspath(workspace or os.getcwd())
    resolved_provider = await runtime._resolve_provider(provider or (spec.provider if spec else ""))  # noqa: SLF001
    resolved_model = model or (spec.model if spec else "") or resolved_provider.default_model
    resolved_model = resolved_model or runtime._deps.settings.default_model  # noqa: SLF001
    adapter = await runtime._deps.provider_manager.get_adapter(resolved_provider.id)  # noqa: SLF001
    tools = spec.tools if spec is not None else ToolConfig()
    max_depth = spec.sub_agents.max_depth if spec is not None else 1
    registry = runtime._build_registry(  # noqa: SLF001
        tools,
        max_depth,
        resolved_workspace,
        adapter,
        resolved_model,
        session_id,
        task_queue,
        event_handler,
        is_sub_agent,
    )
    raw_bridge = bridge_cls(runtime._deps.mcp_manager, registry)  # noqa: SLF001
    if spec is None:
        await raw_bridge.sync_all()
        bridge = raw_bridge
    else:
        bridge = FilteredBridge(
            raw_bridge,
            registry,
            set(tools.allowed_tools),
            extract_required_mcp_servers(spec),
        )
        await bridge.sync_all()
    runner = PlanExecuteRunner(
        adapter,
        registry,
        PlanStore(),
        TodoStore(),
        renderer or SilentPlanRenderer(),
        session_id,
        bridge=bridge,
        agent_spec=spec,
        owner_id=owner_id,
    )
    _patch_plan_runner(runner, runtime, spec, resolved_workspace, event_handler)
    return runner


def _patch_plan_runner(
    runner: PlanExecuteRunner,
    runtime: AgentRuntime,
    spec: AgentSpec | None,
    workspace: str,
    event_handler: AgentEventHandler | None,
) -> None:
    spec_prompt = runtime._compose_system_prompt(workspace, spec.system_prompt) if spec else ""  # noqa: SLF001
    original_prompt = runner._build_step_prompt  # noqa: SLF001
    original_loop = runner._build_step_loop  # noqa: SLF001

    def build_step_prompt(context: object, include_instruction: bool = True) -> tuple[str, str]:
        system_prompt, user_message = original_prompt(
            context, include_instruction=include_instruction
        )
        if spec_prompt:
            system_prompt = f"{spec_prompt}\n\n{system_prompt}"
        return system_prompt, user_message

    def build_step_loop(todo_step: object, context: object) -> AgentLoop:
        loop = original_loop(todo_step, context)
        if spec is not None:
            loop._config.max_iterations = spec.max_iterations  # noqa: SLF001
            loop._config.timeout_seconds = spec.timeout_seconds  # noqa: SLF001
        if event_handler is not None:
            loop.on(event_handler)
        return loop

    runner._build_step_prompt = build_step_prompt  # noqa: SLF001
    runner._build_step_loop = build_step_loop  # noqa: SLF001


__all__ = ["create_runtime_runner"]
