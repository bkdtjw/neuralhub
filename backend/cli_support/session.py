from __future__ import annotations

import os
import signal

from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError, LLMError
from backend.common.types import AgentConfig, AgentEventHandler, Message, ProviderConfig
from backend.config import get_redis, init_redis, settings
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s05_skills import AgentRuntime, AgentRuntimeDeps, SkillLoader, SpecRegistry
from backend.core.s02_tools.mcp import MCPServerManager, MCPToolBridge
from backend.core.sub_agent_queue import create_sub_agent_task_queue
from backend.core.system_prompt import build_system_prompt
from backend.storage import SubAgentTaskStore, init_db

from .models import CliArgs, CliError, CliSession, CliState, SessionUpdate


def _resolve_workspace(workspace: str) -> str:
    resolved = os.path.abspath(os.path.expanduser(workspace))
    if not os.path.isdir(resolved):
        raise CliError("CLI_WORKSPACE_NOT_FOUND", f"Workspace not found: {resolved}")
    return resolved


async def _resolve_provider(manager: ProviderManager, provider: str | None) -> ProviderConfig:
    providers = await manager.list_all()
    if not providers:
        raise CliError("CLI_PROVIDER_MISSING", "No provider is configured.")
    if provider is None:
        return next((item for item in providers if item.is_default), providers[0])
    for item in providers:
        if provider in {item.id, item.name} or provider.lower() == item.name.lower():
            return item
    raise CliError("CLI_PROVIDER_NOT_FOUND", f"Provider not found: {provider}")


def _build_registry(state: CliState) -> ToolRegistry:
    registry = ToolRegistry()
    return registry


def _clone_messages(
    messages: list[Message],
    system_prompt: str,
    clear_provider_metadata: bool,
) -> list[Message]:
    restored = [Message(role="system", content=system_prompt)]
    for message in messages:
        if message.role == "system":
            continue
        cloned = message.model_copy(deep=True)
        if clear_provider_metadata:
            cloned.provider_metadata = {}
        restored.append(cloned)
    return restored


async def create_session(
    args: CliArgs,
    manager: ProviderManager | None = None,
    mcp_manager: MCPServerManager | None = None,
    event_handler: AgentEventHandler | None = None,
) -> CliSession:
    try:
        await init_db()
        await init_redis()
        provider_manager = manager or ProviderManager()
        resolved_mcp_manager = mcp_manager or MCPServerManager(config_path=args.mcp_config)
        workspace = _resolve_workspace(args.workspace)
        provider = await _resolve_provider(provider_manager, args.provider)
        adapter = await provider_manager.get_adapter(provider.id)
        spec_registry = SpecRegistry()
        for spec in SkillLoader().load_all():
            spec_registry.register(spec)
        agent_runtime = AgentRuntime(
            AgentRuntimeDeps(
                provider_manager=provider_manager,
                mcp_manager=resolved_mcp_manager,
                settings=settings,
                spec_registry=spec_registry,
            )
        )
        redis = get_redis()
        task_queue = (
            create_sub_agent_task_queue(redis, persistence=SubAgentTaskStore())
            if redis is not None
            else None
        )
        registry = _build_registry(
            CliState(
                provider_id=provider.id,
                provider_name=provider.name,
                model=args.model or provider.default_model,
                workspace=workspace,
                permission_mode=args.permission_mode,
            )
        )
        register_builtin_tools(
            registry,
            workspace,
            mode=args.permission_mode,
            adapter=adapter,
            default_model=args.model or provider.default_model,
            feishu_webhook_url=settings.feishu_webhook_url or None,
            feishu_secret=settings.feishu_webhook_secret or None,
            youtube_api_key=settings.youtube_api_key or None,
            youtube_proxy_url=settings.youtube_proxy_url or None,
            twitter_username=settings.twitter_username or None,
            twitter_email=settings.twitter_email or None,
            twitter_password=settings.twitter_password or None,
            twitter_proxy_url=settings.twitter_proxy_url or None,
            twitter_cookies_file=settings.twitter_cookies_file or None,
            agent_runtime=agent_runtime,
            spec_registry=spec_registry,
            task_queue=task_queue,
            event_handler=event_handler,
        )
        bridge = MCPToolBridge(resolved_mcp_manager, registry)
        await bridge.sync_all()
        loop = AgentLoop(
            config=AgentConfig(
                model=args.model or provider.default_model,
                provider=provider.id,
                system_prompt=build_system_prompt(workspace),
            ),
            adapter=adapter,
            tool_registry=registry,
        )
        if event_handler is not None:
            loop.on(event_handler)
        return CliSession(
            manager=provider_manager,
            mcp_manager=resolved_mcp_manager,
            mcp_bridge=bridge,
            loop=loop,
            registry=registry,
            state=CliState(
                provider_id=provider.id,
                provider_name=provider.name,
                model=args.model or provider.default_model,
                available_models=list(provider.available_models),
                workspace=workspace,
                permission_mode=args.permission_mode,
            ),
            event_handler=event_handler,
            agent_runtime=agent_runtime,
            spec_registry=spec_registry,
            task_queue=task_queue,
        )
    except (CliError, LLMError):
        raise
    except Exception as exc:
        raise CliError("CLI_SESSION_CREATE_ERROR", str(exc)) from exc


async def rebuild_session(session: CliSession, update: SessionUpdate) -> CliSession:
    try:
        rebuilt = await create_session(
            CliArgs(
                workspace=update.workspace or session.state.workspace,
                model=update.model or session.state.model,
                provider=update.provider or session.state.provider_id,
                permission_mode=update.permission_mode or session.state.permission_mode,
            ),
            manager=session.manager,
            mcp_manager=session.mcp_manager,
            event_handler=session.event_handler,
        )
        if update.preserve_history and session.loop.messages:
            rebuilt.loop.message_history.restore(
                _clone_messages(
                    session.loop.messages,
                    rebuilt.loop._config.system_prompt,  # noqa: SLF001
                    update.clear_provider_metadata,
                )
            )
        return rebuilt
    except (CliError, LLMError):
        raise
    except Exception as exc:
        raise CliError("CLI_SESSION_REBUILD_ERROR", str(exc)) from exc


async def run_request(session: CliSession, user_input: str) -> None:
    previous_handler = signal.getsignal(signal.SIGINT)
    interrupted = False

    def _handle_sigint(signum: int, frame: object | None) -> None:
        nonlocal interrupted
        if interrupted:
            return
        interrupted = True
        session.loop.abort()
        print("\n[interrupt] 已请求中断，等待当前步骤结束...")

    try:
        signal.signal(signal.SIGINT, _handle_sigint)
        try:
            if session.mcp_bridge is not None and session.mcp_bridge.needs_sync():
                await session.mcp_bridge.sync_if_needed()
            await session.loop.run(user_input)
        except AgentError as exc:
            if interrupted and exc.code == "LOOP_ABORTED":
                print("[interrupt] 当前请求已中断。")
                return
            raise
    except (AgentError, LLMError):
        raise
    except Exception as exc:
        raise CliError("CLI_REQUEST_ERROR", str(exc)) from exc
    finally:
        signal.signal(signal.SIGINT, previous_handler)


__all__ = ["create_session", "rebuild_session", "run_request"]
