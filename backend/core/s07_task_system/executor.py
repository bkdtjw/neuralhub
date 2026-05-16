from __future__ import annotations

import os
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.common.logging import bound_log_context, get_logger, new_trace_id
from backend.common.metrics import incr
from backend.common.types import AgentConfig, Message
from backend.config.settings import settings as app_settings
from backend.core.s01_agent_loop import AgentLoop, CheckpointFn
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPToolBridge
from backend.core.system_prompt import build_system_prompt
from backend.storage.session_store import SessionStore

from .executor_errors import TaskExecutionError
from .executor_models import TaskExecutorDeps
from .executor_support import build_card_meta, save_markdown, save_report
from .models import ScheduledTask

logger = get_logger(component="task_executor")
_BEIJING = ZoneInfo("Asia/Shanghai")
_SUB_AGENT_TOOL_CALLS_PREFIX = "[meta] sub_agent_tool_calls="


class TaskExecutor:
    def __init__(self, deps: TaskExecutorDeps) -> None:
        self._deps = deps

    async def execute(self, task: ScheduledTask) -> str:
        with bound_log_context(trace_id=new_trace_id(), session_id=f"scheduled-task:{task.id}"):
            run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            checkpoint_session_id = f"task-{task.id}-{run_id}"
            agent, adapter = await self._create_loop(task, checkpoint_session_id)
            started_at = datetime.now(_BEIJING)
            started_perf = monotonic()
            error_message = ""
            logger.info(
                "task_execute_start",
                task_id=task.id,
                task_name=task.name,
                model=agent._config.model,  # noqa: SLF001
                provider_id=agent._config.provider,  # noqa: SLF001
                spec_id=task.spec_id or "",
            )
            try:
                result = await agent.run(task.prompt)
                content = getattr(result, "content", "") or str(result)
                status = "success"
                await incr("task_successes")
            except Exception as exc:
                content = ""
                status = "error"
                error_message = str(exc)
                await incr("task_failures")
                logger.exception(
                    "task_execute_error",
                    task_id=task.id,
                    task_name=task.name,
                    error=str(exc),
                )
            finished_at = datetime.now(_BEIJING)
            main_tool_call_count = sum(
                len(message.tool_calls)
                for message in agent.messages
                if message.role == "assistant" and message.tool_calls
            )
            sub_tool_call_count = sum(
                _extract_sub_agent_tool_calls(result.output)
                for message in agent.messages
                for result in (message.tool_results or [])
            )
            tool_call_count = main_tool_call_count + sub_tool_call_count
            success_count = _count_successful_tool_results(agent.messages)
            meta: dict[str, Any] = {
                "status": status,
                "tool_call_count": tool_call_count,
                "success_count": success_count,
                "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": finished_at.strftime("%Y-%m-%d %H:%M:%S"),
                "duration": str(finished_at - started_at),
                "model": agent._config.model,  # noqa: SLF001
                "provider_id": agent._config.provider,  # noqa: SLF001
            }
            report_path = await self._save_report(task, content, meta)
            logger.info("task_report_saved", task_id=task.id, path=str(report_path))
            await self._persist_session(task, agent, checkpoint_session_id, run_id)
            if status == "success":
                logger.info(
                    "task_execute_end",
                    task_id=task.id,
                    task_name=task.name,
                    duration_ms=int((monotonic() - started_perf) * 1000),
                    tool_call_count=tool_call_count,
                )
            if task.notify.feishu:
                sent = await self._notify_feishu(
                    task,
                    adapter,
                    content,
                    meta,
                    report_path,
                    finished_at,
                    agent.messages,
                )
                logger.info("task_feishu_notify", task_id=task.id, success=sent)
            if task.output.save_markdown:
                try:
                    path = self._save_markdown(task, content)
                    logger.info("task_report_saved", task_id=task.id, path=str(path))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "task_markdown_save_failed",
                        task_id=task.id,
                        error=str(exc),
                    )
            if status != "success":
                raise TaskExecutionError(error_message or "Task execution failed", content)
            return content

    async def _create_loop(self, task: ScheduledTask, checkpoint_session_id: str) -> tuple[AgentLoop, Any]:
        if task.spec_id:
            return await self._create_spec_loop(task, checkpoint_session_id)
        return await self._create_prompt_loop(task, checkpoint_session_id)

    async def _create_spec_loop(self, task: ScheduledTask, checkpoint_session_id: str) -> tuple[AgentLoop, Any]:
        if self._deps.agent_runtime is None:
            raise RuntimeError("Task executor agent runtime is not configured")
        store = SessionStore()
        loop = await self._deps.agent_runtime.create_loop_from_id(
            task.spec_id,
            workspace=os.getcwd(),
            session_id=f"scheduled-task:{task.id}",
            task_queue=self._deps.task_queue,
            checkpoint_fn=self._task_checkpoint_fn(store, checkpoint_session_id),
        )
        adapter = await self._deps.provider_manager.get_adapter(loop._config.provider)  # noqa: SLF001
        await self._ensure_task_session(store, task, checkpoint_session_id, loop)
        return loop, adapter

    async def _create_prompt_loop(self, task: ScheduledTask, checkpoint_session_id: str) -> tuple[AgentLoop, Any]:
        provider_id, adapter = await self._get_adapter()
        registry = ToolRegistry()
        self._register_tools(registry, adapter)
        bridge = MCPToolBridge(self._deps.mcp_manager, registry)
        await bridge.sync_all()
        system_prompt = build_system_prompt(os.getcwd())
        store = SessionStore()
        agent = AgentLoop(
            config=AgentConfig(
                model=app_settings.default_model,
                provider=provider_id,
                system_prompt=system_prompt,
                session_id=f"scheduled-task:{task.id}",
            ),
            adapter=adapter,
            tool_registry=registry,
            checkpoint_fn=self._task_checkpoint_fn(store, checkpoint_session_id),
        )
        await self._ensure_task_session(store, task, checkpoint_session_id, agent)
        return agent, adapter

    async def _get_adapter(self) -> tuple[str, Any]:
        providers = await self._deps.provider_manager.list_all()
        if not providers:
            raise RuntimeError("No provider configured")
        default = next((provider for provider in providers if provider.is_default), providers[0])
        return default.id, await self._deps.provider_manager.get_adapter(default.id)

    def _register_tools(self, registry: ToolRegistry, adapter: Any) -> None:
        register_builtin_tools(
            registry,
            workspace=os.getcwd(),
            mode="auto",
            adapter=adapter,
            default_model=app_settings.default_model,
            feishu_webhook_url=app_settings.feishu_webhook_url or None,
            feishu_secret=app_settings.feishu_webhook_secret or None,
            youtube_api_key=app_settings.youtube_api_key or None,
            youtube_proxy_url=app_settings.youtube_proxy_url or None,
            twitter_username=app_settings.twitter_username or None,
            twitter_email=app_settings.twitter_email or None,
            twitter_password=app_settings.twitter_password or None,
            twitter_proxy_url=app_settings.twitter_proxy_url or None,
            twitter_cookies_file=app_settings.twitter_cookies_file or None,
            spec_registry=self._spec_registry(),
            task_queue=self._deps.task_queue,
        )

    def _spec_registry(self) -> Any:
        runtime_deps = getattr(self._deps.agent_runtime, "_deps", None)
        return getattr(runtime_deps, "spec_registry", None)

    def _task_checkpoint_fn(self, store: SessionStore, session_id: str) -> CheckpointFn:
        async def checkpoint(_sid: str, message: Message) -> None:
            await store.add_messages(session_id, [message])

        return checkpoint

    async def _ensure_task_session(
        self,
        store: SessionStore,
        task: ScheduledTask,
        session_id: str,
        agent: AgentLoop,
    ) -> None:
        try:
            system_prompt = (
                agent.messages[0].content
                if agent.messages and agent.messages[0].role == "system"
                else agent._config.system_prompt  # noqa: SLF001
            )
            await store.ensure_session(
                session_id,
                model=agent._config.model,  # noqa: SLF001
                provider=agent._config.provider,  # noqa: SLF001
                system_prompt=system_prompt,
                max_tokens=16384,
                title=f"{task.name} @ {session_id.removeprefix(f'task-{task.id}-')}",
                workspace="scheduled_task",
            )
        except Exception:
            logger.warning("task_persist_failed", task_id=task.id)

    async def _persist_session(
        self,
        task: ScheduledTask,
        agent: AgentLoop,
        session_id: str,
        run_id: str,
    ) -> None:
        try:
            store = SessionStore()
            await self._ensure_task_session(store, task, session_id, agent)
            await store.save_messages(session_id, agent.messages)
        except Exception:
            logger.warning("task_persist_failed", task_id=task.id, run_id=run_id)

    async def _save_report(self, task: ScheduledTask, content: str, meta: dict[str, Any]) -> Any:
        return await save_report(task, content, meta)

    def _save_markdown(self, task: ScheduledTask, content: str) -> Any:
        return save_markdown(task, content)

    async def _notify_feishu(
        self,
        task: ScheduledTask,
        adapter: Any,
        content: str,
        meta: dict[str, Any],
        report_path: Any,
        finished_at: datetime,
        messages: list[Any],
    ) -> bool:
        from .card_notify import extract_tool_names, try_send_card

        model = str(meta.get("model") or app_settings.default_model)
        tool_names = extract_tool_names(messages)
        card_meta = build_card_meta(task, meta, report_path, finished_at)
        chat_id = app_settings.feishu_chat_id
        if self._deps.feishu_client and chat_id:
            try:
                sent = await try_send_card(
                    adapter=adapter,
                    model=model,
                    agent_reply=content,
                    meta=card_meta,
                    tool_names=tool_names,
                    task_card_scenario=task.card_scenario,
                    feishu_client=self._deps.feishu_client,
                    chat_id=chat_id,
                )
                if sent:
                    return True
            except Exception:
                logger.warning("task_feishu_card_failed", task_id=task.id)
        webhook_url = task.notify.feishu_webhook_url or app_settings.feishu_webhook_url
        if not webhook_url:
            return False
        sent = await try_send_card(
            adapter=adapter,
            model=model,
            agent_reply=content,
            meta=card_meta,
            tool_names=tool_names,
            task_card_scenario=task.card_scenario,
            webhook_url=webhook_url,
            webhook_secret=app_settings.feishu_webhook_secret or None,
        )
        if sent:
            return True
        return await self._send_feishu_text(task, content)

    async def _send_feishu_text(self, task: ScheduledTask, content: str) -> bool:
        webhook_url = task.notify.feishu_webhook_url or app_settings.feishu_webhook_url
        if not webhook_url:
            return False
        from backend.core.s02_tools.builtin.feishu_notify import _build_request_body

        body = _build_request_body(
            content=content[:4000],
            title=task.notify.feishu_title or task.name,
            secret=app_settings.feishu_webhook_secret or None,
        )
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                await client.post(webhook_url, json=body)
            return True
        except Exception as exc:
            logger.error("task_feishu_notify_failed", task_id=task.id, error=str(exc))
            return False

def _extract_sub_agent_tool_calls(output: str) -> int:
    for line in output.splitlines():
        if not line.startswith(_SUB_AGENT_TOOL_CALLS_PREFIX):
            continue
        try:
            return int(line.removeprefix(_SUB_AGENT_TOOL_CALLS_PREFIX).strip())
        except ValueError:
            return 0
    return 0


def _count_successful_tool_results(messages: list[Any]) -> int:
    return sum(
        1
        for message in messages
        for result in (getattr(message, "tool_results", None) or [])
        if not getattr(result, "is_error", False)
    )


__all__ = ["TaskExecutor"]
