from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.api.routes.mcp import mcp_server_manager
from backend.api.routes.providers import provider_manager
from backend.common.errors import AgentError
from backend.common.types import AgentConfig, AgentEvent, Message
from backend.config.settings import settings as app_settings
from backend.core.s01_agent_loop import AgentLoop, CheckpointFn
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPToolBridge
from backend.core.s05_skills import AgentRuntime, SpecRegistry
from backend.core.system_prompt import build_system_prompt
from backend.core.task_queue import TaskQueue
from backend.storage import SessionStore

from .websocket_support import LoopSettings, event_to_ws_message, restore_messages


class CreateLoopInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    settings: LoopSettings
    store: SessionStore | None = None
    previous_loop: AgentLoop | None = None
    previous_settings: LoopSettings | None = None
    agent_runtime: AgentRuntime | None = None
    spec_registry: SpecRegistry | None = None
    task_queue: TaskQueue | None = None
    event_sender: Callable[[dict[str, Any]], Awaitable[None]]


class RuntimeComponentsInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: LoopSettings
    agent_runtime: AgentRuntime | None = None
    spec_registry: SpecRegistry | None = None
    task_queue: TaskQueue | None = None
    event_sender: Callable[[dict[str, Any]], Awaitable[None]]


class RuntimeComponents(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    adapter: Any
    registry: ToolRegistry
    bridge: MCPToolBridge


async def create_loop(payload: CreateLoopInput) -> AgentLoop:
    try:
        loop = await _build_loop(payload)
        messages = await _load_messages(payload, loop._config.system_prompt)
        if messages:
            loop._messages = messages  # noqa: SLF001

        async def on_event(event: AgentEvent) -> None:
            await payload.event_sender(event_to_ws_message(event))

        loop.on(on_event)
        return loop
    except Exception as exc:  # noqa: BLE001
        raise AgentError("WS_CREATE_LOOP_ERROR", str(exc)) from exc


async def _build_loop(payload: CreateLoopInput) -> AgentLoop:
    settings = payload.settings
    checkpoint_fn = await _make_checkpoint_fn(payload.session_id, payload.store)

    if settings.spec_id:
        if payload.agent_runtime is None:
            raise AgentError("WS_RUNTIME_MISSING", "agent runtime is not available")

        async def forward_tool_event(event: AgentEvent) -> None:
            try:
                await payload.event_sender(event_to_ws_message(event))
            except Exception:
                return

        return await payload.agent_runtime.create_loop_from_id(
            settings.spec_id,
            workspace=settings.workspace or "",
            session_id=payload.session_id,
            model=settings.model,
            provider=settings.provider_id or "",
            task_queue=payload.task_queue,
            event_handler=forward_tool_event,
            checkpoint_fn=checkpoint_fn,
        )
    system_prompt = build_system_prompt(settings.workspace)
    components = await create_runtime_components(
        RuntimeComponentsInput(
            settings=settings,
            agent_runtime=payload.agent_runtime,
            spec_registry=payload.spec_registry,
            task_queue=payload.task_queue,
            event_sender=payload.event_sender,
        )
    )
    loop = AgentLoop(
        config=AgentConfig(
            model=settings.model,
            system_prompt=system_prompt,
            session_id=payload.session_id,
        ),
        adapter=components.adapter,
        tool_registry=components.registry,
        checkpoint_fn=checkpoint_fn,
    )
    setattr(loop, "_bridge", components.bridge)  # noqa: B010, SLF001
    return loop


async def create_runtime_components(payload: RuntimeComponentsInput) -> RuntimeComponents:
    try:

        async def forward_tool_event(event: AgentEvent) -> None:
            try:
                await payload.event_sender(event_to_ws_message(event))
            except Exception:
                return

        settings = payload.settings
        adapter = await provider_manager.get_adapter(settings.provider_id)
        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            settings.workspace,
            mode=settings.permission_mode,
            adapter=adapter,
            default_model=settings.model,
            feishu_webhook_url=app_settings.feishu_webhook_url or None,
            feishu_secret=app_settings.feishu_webhook_secret or None,
            youtube_api_key=app_settings.youtube_api_key or None,
            youtube_proxy_url=app_settings.youtube_proxy_url or None,
            twitter_username=app_settings.twitter_username or None,
            twitter_email=app_settings.twitter_email or None,
            twitter_password=app_settings.twitter_password or None,
            twitter_proxy_url=app_settings.twitter_proxy_url or None,
            twitter_cookies_file=app_settings.twitter_cookies_file or None,
            agent_runtime=payload.agent_runtime,
            spec_registry=payload.spec_registry,
            task_queue=payload.task_queue,
            event_handler=forward_tool_event,
        )
        bridge = MCPToolBridge(mcp_server_manager, registry)
        await bridge.sync_all()
        return RuntimeComponents(adapter=adapter, registry=registry, bridge=bridge)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("WS_RUNTIME_COMPONENTS_ERROR", str(exc)) from exc


async def _make_checkpoint_fn(
    session_id: str,
    store: SessionStore | None,
) -> CheckpointFn | None:
    if store is None:
        return None

    async def checkpoint(sid: str, message: Message) -> None:
        await store.add_messages(sid or session_id, [message])

    return checkpoint


async def _load_messages(
    payload: CreateLoopInput,
    system_prompt: str,
) -> list[Any]:
    if payload.settings.spec_id and payload.previous_loop is None:
        return []
    if (
        payload.previous_settings is not None
        and payload.previous_settings.spec_id != payload.settings.spec_id
    ):
        return []
    if payload.store is not None:
        stored = await payload.store.get_messages(payload.session_id)
    else:
        stored = payload.previous_loop.messages if payload.previous_loop is not None else []
    if not stored:
        return []
    return restore_messages(
        stored,
        system_prompt,
        clear_provider_metadata=payload.previous_settings is not None
        and payload.previous_settings.provider_id != payload.settings.provider_id,
    )


__all__ = [
    "CreateLoopInput",
    "RuntimeComponents",
    "RuntimeComponentsInput",
    "create_loop",
    "create_runtime_components",
]
