from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from backend.adapters.base import LLMAdapter
from backend.common.types import AgentEventHandler, LLMRequest, Message
from backend.config.settings import settings as app_settings
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import (
    AgentDefinitionLoader,
    SubAgentLifecycle,
    SubAgentSpawner,
)

from .bash import create_bash_tool
from .dispatch_agent import create_dispatch_agent_tool
from .feishu_notify import create_feishu_notify_tool
from .file_edit import create_file_edit_tool, create_str_replace_tool
from .file_glob import create_glob_tool
from .file_grep import create_grep_tool
from .file_read import create_read_tool
from .file_write import create_write_tool

if TYPE_CHECKING:
    from backend.core.s05_skills import AgentRuntime, SpecRegistry
    from backend.core.task_queue import TaskQueue

PermissionMode = Literal["readonly", "auto", "full"]


def register_builtin_tools(
    registry: ToolRegistry,
    workspace: str | None,
    mode: PermissionMode = "auto",
    adapter: LLMAdapter | None = None,
    default_model: str = "",
    agents_dir: str | None = None,
    feishu_webhook_url: str | None = None,
    feishu_secret: str | None = None,
    youtube_api_key: str | None = None,
    youtube_proxy_url: str | None = None,
    twitter_username: str | None = None,
    twitter_email: str | None = None,
    twitter_password: str | None = None,
    twitter_proxy_url: str | None = None,
    twitter_cookies_file: str | None = None,
    agent_runtime: AgentRuntime | None = None,
    spec_registry: SpecRegistry | None = None,
    task_queue: TaskQueue | None = None,
    event_handler: AgentEventHandler | None = None,
    is_sub_agent: bool = False,
    parent_task_id: str = "",
    browser_login_manager: Any | None = None,
    browser_login_chat_id: str = "",
) -> None:
    """根据权限模式注册不同的工具集。"""
    tools = (
        [create_read_tool(workspace), create_glob_tool(workspace), create_grep_tool(workspace)]
        if workspace
        else []
    )

    if workspace and mode in ("auto", "full"):
        tools.append(create_str_replace_tool(workspace))
        tools.append(create_file_edit_tool(workspace))
        tools.append(create_write_tool(workspace))
        tools.append(create_bash_tool(workspace))
        if adapter is not None and not is_sub_agent:
            loader = AgentDefinitionLoader(agents_dir)
            spawner = SubAgentSpawner(adapter, registry, loader, default_model)
            lifecycle = SubAgentLifecycle(timeout=120.0)
            tools.append(create_dispatch_agent_tool(spawner, lifecycle))
            try:
                from backend.core.s04_sub_agents import OrchestratorConfig

                from .orchestrate_agents import create_orchestrate_agents_tool
            except ImportError:
                pass
            else:
                tools.append(
                    create_orchestrate_agents_tool(
                        adapter=adapter,
                        parent_registry=registry,
                        config=OrchestratorConfig(
                            workspace=workspace,
                            default_model=default_model,
                            agents_dir=agents_dir,
                        ),
                    )
                )

    # YouTube 搜索工具 - API Key 版本（优先）
    resolved_youtube_api_key = youtube_api_key or os.environ.get("YOUTUBE_API_KEY", "")
    youtube_tool_registered = False
    if resolved_youtube_api_key:
        try:
            from .youtube_search import create_youtube_search_tool

            resolved_youtube_proxy = youtube_proxy_url or os.environ.get("YOUTUBE_PROXY_URL", "")
            tools.append(
                create_youtube_search_tool(
                    api_key=resolved_youtube_api_key,
                    proxy_url=resolved_youtube_proxy,
                )
            )
            youtube_tool_registered = True
        except ImportError:
            pass

    # YouTube 搜索工具 - yt-dlp 版本（无需 API Key）
    if not youtube_tool_registered:
        try:
            from .youtube_search_ytdlp import (
                create_youtube_search_ytdlp_tool,
                create_youtube_subtitle_tool,
            )
            tools.append(create_youtube_search_ytdlp_tool())
            tools.append(create_youtube_subtitle_tool())
        except ImportError:
            pass

    resolved_twitter_username = twitter_username or os.environ.get("TWITTER_USERNAME", "")
    resolved_twitter_email = twitter_email or os.environ.get("TWITTER_EMAIL", "")
    resolved_twitter_password = twitter_password or os.environ.get("TWITTER_PASSWORD", "")
    if (resolved_twitter_username or resolved_twitter_email) and resolved_twitter_password:
        try:
            from .x_client import XClientConfig
            from .x_search import create_x_search_tool

            tools.append(
                create_x_search_tool(
                    XClientConfig(
                        username=resolved_twitter_username,
                        email=resolved_twitter_email,
                        password=resolved_twitter_password,
                        proxy_url=twitter_proxy_url or os.environ.get("TWITTER_PROXY_URL", ""),
                        cookies_file=twitter_cookies_file
                        or os.environ.get("TWITTER_COOKIES_FILE", "twitter_cookies.json"),
                    )
                )
            )
        except ImportError:
            pass
        try:
            from .collect_and_process import (
                CollectAndProcessConfig,
                create_collect_and_process_tool,
            )
            from .x_client import XClientConfig

            tools.append(
                create_collect_and_process_tool(
                    CollectAndProcessConfig(
                        x_config=XClientConfig(
                            username=resolved_twitter_username,
                            email=resolved_twitter_email,
                            password=resolved_twitter_password,
                            proxy_url=twitter_proxy_url or os.environ.get("TWITTER_PROXY_URL", ""),
                            cookies_file=twitter_cookies_file
                            or os.environ.get("TWITTER_COOKIES_FILE", "twitter_cookies.json"),
                        ),
                        youtube_api_key=resolved_youtube_api_key,
                        youtube_proxy_url=(
                            youtube_proxy_url or os.environ.get("YOUTUBE_PROXY_URL", "")
                        ),
                    )
                )
            )
        except ImportError:
            pass

    feishu_url = feishu_webhook_url or os.environ.get("FEISHU_WEBHOOK_URL", "")
    resolved_feishu_secret = feishu_secret or os.environ.get("FEISHU_WEBHOOK_SECRET", "")
    if feishu_url:
        tools.append(create_feishu_notify_tool(feishu_url, resolved_feishu_secret or None))

    try:
        from backend.adapters.role_router import RoleRouter

        from .browser_agent import create_browse_web_tool

        tools.append(
            create_browse_web_tool(
                RoleRouter(),
                login_manager=browser_login_manager,
                chat_id=browser_login_chat_id,
            )
        )
    except ImportError:
        pass

    # 灵犀金融数据Skills
    try:
        from .lingxi import (
            create_lingxi_financial_search_tool,
            create_lingxi_ranklist_tool,
            create_lingxi_realtime_marketdata_tool,
            create_lingxi_smart_stock_selection_tool,
        )

        tools.append(create_lingxi_financial_search_tool())
        tools.append(create_lingxi_realtime_marketdata_tool())
        tools.append(create_lingxi_ranklist_tool())
        tools.append(create_lingxi_smart_stock_selection_tool())
    except ImportError:
        pass
    if spec_registry is not None and not is_sub_agent:
        from .query_specs import create_query_specs_tool

        tools.append(create_query_specs_tool(spec_registry))
    if not is_sub_agent and task_queue is not None and spec_registry is not None:
        from .spawn_agent import create_spawn_agent_tool
        from .spawn_agent_support import SpawnAgentDeps

        tools.append(
            create_spawn_agent_tool(
                SpawnAgentDeps(
                    task_queue=task_queue,
                    spec_registry=spec_registry,
                    workspace=workspace or "",
                    event_handler=event_handler,
                    parent_task_id=parent_task_id,
                )
            )
        )

    proxy_api_url = os.environ.get("MIHOMO_API_URL", "http://127.0.0.1:9090")
    proxy_api_secret = os.environ.get("MIHOMO_SECRET", "")
    try:
        from .proxy_lifecycle_tools import create_proxy_off_tool, create_proxy_on_tool
        from .proxy_tools import (
            create_proxy_chain_tool,
            create_proxy_optimize_tool,
            create_proxy_status_tool,
            create_proxy_switch_tool,
            create_proxy_test_tool,
        )

        tools.append(create_proxy_status_tool(proxy_api_url, proxy_api_secret))
        tools.append(create_proxy_test_tool(proxy_api_url, proxy_api_secret))
        tools.append(create_proxy_switch_tool(proxy_api_url, proxy_api_secret))
        mihomo_config_path = app_settings.mihomo_config_path or os.environ.get(
            "MIHOMO_CONFIG_PATH",
            "",
        )
        if mihomo_config_path:
            config_dir = Path(mihomo_config_path).resolve().parent
            custom_nodes_path = (
                app_settings.mihomo_custom_nodes_path
                or os.environ.get("MIHOMO_CUSTOM_NODES_PATH", "")
                or str(config_dir / "custom_nodes.yaml")
            )
            sub_path = app_settings.mihomo_sub_path or os.environ.get(
                "MIHOMO_SUB_PATH",
                str(config_dir / "sub_raw.yaml"),
            )
            tools.append(
                create_proxy_optimize_tool(
                    mihomo_config_path,
                    proxy_api_url,
                    proxy_api_secret,
                )
            )
            tools.append(
                create_proxy_chain_tool(
                    mihomo_config_path,
                    proxy_api_url,
                    proxy_api_secret,
                    custom_nodes_path=custom_nodes_path,
                )
            )
            try:
                from .proxy_scheduler_tools import create_proxy_scheduler_tool

                llm_callback = None
                if adapter is not None and default_model:
                    async def _llm_call(prompt: str) -> str:
                        response = await adapter.complete(
                            LLMRequest(
                                model=default_model,
                                messages=[Message(role="user", content=prompt)],
                            )
                        )
                        return response.content if response else ""
                    llm_callback = _llm_call
                tools.append(
                    create_proxy_scheduler_tool(
                        api_url=proxy_api_url,
                        api_secret=proxy_api_secret,
                        config_path=mihomo_config_path,
                        custom_nodes_path=custom_nodes_path,
                        llm_callback=llm_callback,
                    )
                )
            except ImportError:
                pass
        mihomo_path = app_settings.mihomo_path or os.environ.get("MIHOMO_PATH", "")
        if mihomo_path and mihomo_config_path:
            config_dir = Path(mihomo_config_path).resolve().parent
            tools.append(
                create_proxy_on_tool(
                    mihomo_path=mihomo_path,
                    config_path=mihomo_config_path,
                    work_dir=app_settings.mihomo_work_dir
                    or os.environ.get("MIHOMO_WORK_DIR", "")
                    or str(config_dir),
                    sub_path=sub_path,
                    custom_nodes_path=custom_nodes_path,
                    api_url=proxy_api_url,
                    secret=proxy_api_secret,
                )
            )
            tools.append(create_proxy_off_tool())
    except ImportError:
        pass

    try:
        from backend.adapters.provider_manager import ProviderManager
        from backend.core.s02_tools.mcp import MCPServerManager
        from backend.core.s07_task_system import TaskExecutor, TaskExecutorDeps
        from backend.core.s07_task_system.store import TaskStore

        from .task_scheduler import create_task_tools

        task_store = TaskStore()
        task_executor = TaskExecutor(
            TaskExecutorDeps(
                provider_manager=ProviderManager(),
                mcp_manager=MCPServerManager(),
                agent_runtime=agent_runtime,
                task_queue=task_queue,
            )
        )
        for defn, exec_fn in create_task_tools(task_store, None, task_executor):
            tools.append((defn, exec_fn))
    except ImportError:
        pass

    for definition, executor in tools:
        registry.register(definition, executor)


__all__ = ["register_builtin_tools", "PermissionMode"]
