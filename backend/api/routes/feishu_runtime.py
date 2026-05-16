from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import AgentConfig
from backend.config import get_redis
from backend.config.settings import settings as app_settings
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPServerManager, MCPToolBridge
from backend.core.system_prompt import build_system_prompt

if TYPE_CHECKING:
    from backend.core.s05_skills import AgentRuntime, SpecRegistry
    from backend.core.task_queue import TaskQueue

logger = get_logger(component="feishu_runtime")

_FEISHU_EVENT_TTL = 86400
_FEISHU_REDIS_RETRIES = 3
BROWSE_WEB_HINT = """

你可以调用 browse_web 工具来自动完成多步骤的网页任务。适合场景：
- 用户要求"打开/查看/查找/抓取"某个网页内容
- 需要登录后才能拿到的信息（前提：已配置 storage_state）
- 多步交互（搜索 → 点结果 → 翻页 → 提取）

调用方式：browse_web(task="自然语言描述任务", domain="可选，用于加载登录态")。
工具返回文字结果。任务可能耗时 30 秒到几分钟，期间无中间反馈。
"""


async def build_agent_loop(
    adapter: Any,
    session_id: str = "",
    model: str | None = None,
    provider: str | None = None,
    system_prompt: str | None = None,
    agent_runtime: AgentRuntime | None = None,
    spec_registry: SpecRegistry | None = None,
    task_queue: TaskQueue | None = None,
    owner_id: str = "",
) -> AgentLoop:
    resolved_model = model or app_settings.default_model
    resolved_system_prompt = system_prompt or build_system_prompt(os.getcwd())
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        workspace=os.getcwd(),
        mode="auto",
        adapter=adapter,
        default_model=resolved_model,
        feishu_webhook_url=app_settings.feishu_webhook_url or None,
        feishu_secret=app_settings.feishu_webhook_secret or None,
        youtube_api_key=app_settings.youtube_api_key or None,
        youtube_proxy_url=app_settings.youtube_proxy_url or None,
        twitter_username=app_settings.twitter_username or None,
        twitter_email=app_settings.twitter_email or None,
        twitter_password=app_settings.twitter_password or None,
        twitter_proxy_url=app_settings.twitter_proxy_url or None,
        twitter_cookies_file=app_settings.twitter_cookies_file or None,
        agent_runtime=agent_runtime,
        spec_registry=spec_registry,
        task_queue=task_queue,
    )
    bridge = MCPToolBridge(MCPServerManager(), registry)
    await bridge.sync_all()
    if registry.has("browse_web"):
        resolved_system_prompt += BROWSE_WEB_HINT
    return AgentLoop(
        config=AgentConfig(
            model=resolved_model,
            provider=provider or "anthropic",
            system_prompt=resolved_system_prompt,
            session_id=session_id,
        ),
        adapter=adapter,
        tool_registry=registry,
        owner_id=owner_id or session_id,
    )


def collect_tool_calls(loop: AgentLoop) -> tuple[set[str], dict[str, dict[str, Any]]]:
    tool_names: set[str] = set()
    tool_args: dict[str, dict[str, Any]] = {}
    for msg in loop.messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_names.add(tool_call.name)
                tool_args[tool_call.name] = tool_call.arguments
    return tool_names, tool_args


class FeishuEventDeduplicator:
    async def seen(self, event_id: str) -> bool:
        try:
            if not event_id:
                return False
            redis = get_redis()
            if redis is None:
                raise AgentError(
                    "FEISHU_REDIS_UNAVAILABLE",
                    "Redis client is required for Feishu event deduplication.",
                )
            last_error: Exception | None = None
            for attempt in range(1, _FEISHU_REDIS_RETRIES + 1):
                try:
                    added = await redis.set(
                        f"feishu:event:{event_id}",
                        "1",
                        nx=True,
                        ex=_FEISHU_EVENT_TTL,
                    )
                    return not bool(added)
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "feishu_dedup_retry",
                        attempt=attempt,
                        max_attempts=_FEISHU_REDIS_RETRIES,
                        error=str(exc),
                    )
                    if attempt < _FEISHU_REDIS_RETRIES:
                        await asyncio.sleep(0.1)
            raise AgentError(
                "FEISHU_DEDUP_ERROR",
                str(last_error) if last_error is not None else "Redis dedup failed",
            ) from last_error
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("FEISHU_DEDUP_ERROR", str(exc)) from exc


__all__ = ["FeishuEventDeduplicator", "build_agent_loop", "collect_tool_calls"]
