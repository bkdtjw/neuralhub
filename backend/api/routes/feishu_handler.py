from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import TYPE_CHECKING, Any

from backend.adapters.provider_manager import ProviderManager
from backend.api.routes.feishu_handler_support import (
    build_feishu_log_context,
    extract_text,
    parse_slash_command,
    resolve_reply_text,
    resolve_session_model,
    split_feishu_reply_text,
)
from backend.api.routes.feishu_runtime import (
    FeishuEventDeduplicator,
    build_agent_loop,
    collect_tool_calls,
)
from backend.api.routes.websocket_support import restore_messages
from backend.common.feishu_card import CardRegistry, FeishuCardError, build_card_content
from backend.common.feishu_card_formatter import CardFormatter
from backend.common.logging import get_logger
from backend.common.metrics import incr
from backend.common.types import Session
from backend.core.s01_agent_loop import AgentLoop, PlanExecuteRunner
from backend.core.s02_tools.builtin.feishu_client import FeishuClient
from backend.storage.session_store import SessionStore

from .feishu_browse_artifacts import send_browse_web_artifacts
from .feishu_knowledge_flow import KbContext, handle_kb_menu, route_kb_file, route_kb_text
from .feishu_menu_state import FeishuMenuState
from .feishu_plan_control import (
    RUNNING_REPLY,
    handle_plan_control_message,
    has_active_plan,
    pause_plan_from_menu,
    stop_active_plan_for_chat,
    stop_plan_from_menu,
    toggle_auto_approve_from_menu,
)
from .feishu_plan_decision import (
    approve_plan_decision,
    cancel_plan_decision,
    find_plan_runner,
    owner_matches,
    reject_plan_decision,
)
from .feishu_plan_resume import handle_plan_resume_gate
from .feishu_plan_support import handle_plan_message, parse_plan_request, run_plan, send_chat_text
from .feishu_session_recorder import (
    FeishuOutboundFileRecord,
    FeishuOutboundTextRecord,
    FeishuRecordConfig,
    FeishuSessionRecorder,
    FeishuSessionRecorderError,
)
from .feishu_tool_approval import attach_feishu_loop_approval

if TYPE_CHECKING:
    from backend.core.s05_skills import AgentRuntime, SpecRegistry
    from backend.core.task_queue import TaskQueue

logger = get_logger(component="feishu_handler")


class FeishuMessageHandler:
    def __init__(
        self,
        feishu_client: FeishuClient,
        provider_manager: ProviderManager,
    ) -> None:
        self._client = feishu_client
        self._pm = provider_manager
        self._sessions: dict[str, AgentLoop] = {}
        self._deduplicator = FeishuEventDeduplicator()
        self._card_registry = CardRegistry()
        self._store = SessionStore()
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._agent_runtime: AgentRuntime | None = None
        self._spec_registry: SpecRegistry | None = None
        self._task_queue: TaskQueue | None = None
        self._plan_runners: dict[str, PlanExecuteRunner] = {}
        self._plan_summaries: dict[str, str] = {}
        self._pending_resume: dict[str, Any] = {}
        self._menu_state = FeishuMenuState()
        self._user_modes = self._menu_state._user_modes  # noqa: SLF001
        self._user_chats = self._menu_state._user_chats  # noqa: SLF001

    def configure_runtime(
        self,
        agent_runtime: AgentRuntime | None,
        spec_registry: SpecRegistry | None,
        task_queue: TaskQueue | None,
    ) -> None:
        self._agent_runtime = agent_runtime
        self._spec_registry = spec_registry
        self._task_queue = task_queue

    async def _handle_plan_message(
        self, chat_id: str, message_text: str, spec_id: str = "", owner_id: str = ""
    ) -> None:
        await handle_plan_message(self, chat_id, message_text, spec_id, owner_id)

    async def _run_plan(self, chat_id: str, runner: PlanExecuteRunner, message: str) -> None:
        await run_plan(self, chat_id, runner, message)

    async def handle_menu_event(self, event_key: str, open_id: str) -> None:
        try:
            event_key = event_key.strip().lstrip("=")
            await self._menu_state.clear_pending(open_id)
            logger.info("feishu_menu_event", event_key=event_key, open_id=open_id)
            chat_id = await self._menu_state.get_chat(open_id)
            if await handle_kb_menu(
                KbContext(self, open_id, chat_id or open_id, ""),
                event_key,
            ):
                return
            if event_key == "plan_mode":
                await self._menu_state.set_mode(open_id, "plan_execute")
                await self._send_to_user(
                    open_id,
                    "已切换到 Plan 模式 ✅\n\n"
                    "请直接发送任务描述，我会先制定计划再逐步执行。\n\n"
                    "如需切回普通模式，点击菜单「普通对话」。",
                )
                return
            if event_key == "direct_mode":
                stopped = await stop_active_plan_for_chat(self, chat_id) if chat_id else False
                await self._menu_state.clear_mode(open_id)
                text = "已切换回普通模式 ✅"
                if stopped:
                    text += "\n\n已停止当前计划，后续消息将按普通对话处理。"
                await self._send_to_user(open_id, text)
                return
            if event_key in {"plan_pause", "plan.pause"}:
                await pause_plan_from_menu(self, open_id)
                return
            if event_key in {"plan_stop", "plan_cancel", "plan.stop"}:
                await stop_plan_from_menu(self, open_id)
                return
            if event_key in {"tool_auto_approve", "tool.auto_approve"}:
                await toggle_auto_approve_from_menu(self, open_id)
                return
            logger.warning("feishu_unknown_menu_event", event_key=event_key, open_id=open_id)
        except Exception:
            logger.exception("feishu_menu_event_failed", event_key=event_key, open_id=open_id)

    async def _send_to_user(self, open_id: str, text: str) -> None:
        try:
            chat_id = await self._menu_state.get_chat(open_id)
            receive_id = chat_id or open_id
            receive_id_type = "chat_id" if chat_id else "open_id"
            logger.info(
                "feishu_send_to_user",
                open_id=open_id,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )
            await self._client.send_message(
                receive_id,
                json.dumps({"text": text}, ensure_ascii=False),
                receive_id_type=receive_id_type,
            )
            if receive_id_type == "chat_id":
                await self._record_outbound_text(receive_id, text, "feishu_send_to_user")
        except Exception as exc:
            logger.warning("feishu_send_to_user_failed", open_id=open_id, error=str(exc))

    def cancel_plan(self, chat_id: str, plan_name: str) -> bool:
        return cancel_plan_decision(self, chat_id, plan_name)

    def approve_plan(self, chat_id: str, plan_name: str, owner_id: str = "") -> bool:
        return approve_plan_decision(self, chat_id, plan_name, owner_id)

    def reject_plan(self, chat_id: str, plan_name: str, owner_id: str = "") -> bool:
        return reject_plan_decision(self, chat_id, plan_name, owner_id)

    def resolve_tool_call(
        self,
        chat_id: str,
        tool_call_id: str,
        approved: bool,
        owner_id: str = "",
    ) -> bool:
        resolver_name = "approve_tool_call" if approved else "reject_tool_call"
        targets: list[Any] = []
        if chat_id in self._plan_runners:
            targets.append(self._plan_runners[chat_id])
        if chat_id in self._sessions:
            targets.append(self._sessions[chat_id])
        targets.extend(self._plan_runners.values())
        targets.extend(self._sessions.values())
        for target in targets:
            if not owner_matches(target, owner_id):
                continue
            resolver = getattr(target, resolver_name, None)
            if callable(resolver) and resolver(tool_call_id):
                return True
        return False

    def _find_plan_runner(self, chat_id: str, plan_name: str) -> PlanExecuteRunner | None:
        return find_plan_runner(self._plan_runners, chat_id, plan_name)

    async def handle_message(self, event: dict[str, Any]) -> None:
        event_id = event.get("header", {}).get("event_id", "")
        msg = event.get("event", {}).get("message", {})
        sender = event.get("event", {}).get("sender", {})
        open_id = sender.get("sender_id", {}).get("open_id", "")
        msg_type = msg.get("message_type", "")
        chat_id = msg.get("chat_id", "")
        message_id = msg.get("message_id", "")
        if open_id and chat_id:
            await self._menu_state.set_chat(open_id, chat_id)
        started_at = monotonic()
        with build_feishu_log_context(chat_id):
            try:
                is_duplicate = await self._seen(event_id)
            except Exception as exc:
                # 去重是尽力而为的优化：Redis 不可用/抖动导致 _seen 抛错时降级为“放行”，
                # 最坏是极少数重复消息被处理两次，远好于整条消息被静默丢弃、用户零反馈。
                is_duplicate = False
                logger.warning(
                    "feishu_dedup_unavailable", event_id=event_id, error=str(exc)
                )
                await incr("feishu_dedup_failures")
            if is_duplicate:
                logger.debug("feishu_event_duplicate", event_id=event_id)
                return
            if sender.get("sender_type") == "bot":
                logger.debug("feishu_message_skipped", chat_id=chat_id, reason="bot_sender")
                return
            logger.info(
                "feishu_message_start", event_id=event_id, chat_id=chat_id, message_type=msg_type
            )
            await incr("feishu_messages")
            owner_id = open_id or chat_id
            if msg_type == "file":
                async with self._chat_lock(chat_id):
                    if await route_kb_file(
                        KbContext(self, owner_id, chat_id, message_id),
                        msg,
                    ):
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                try:
                    await self._reply(message_id, json.dumps({"text": "暂不支持该消息类型"}))
                except Exception:
                    pass
                return
            text = extract_text(msg, msg_type)
            if text is None:
                try:
                    await self._reply(message_id, json.dumps({"text": "暂不支持该消息类型"}))
                except Exception:
                    pass
                logger.info(
                    "feishu_message_end",
                    chat_id=chat_id,
                    duration_ms=int((monotonic() - started_at) * 1000),
                )
                return

            async with self._chat_lock(chat_id):
                loop: AgentLoop | None = None
                should_persist = False
                try:
                    if await route_kb_text(KbContext(self, owner_id, chat_id, message_id), text):
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                    if await handle_plan_resume_gate(self, owner_id, chat_id, text):
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                    if has_active_plan(self, chat_id):
                        if await handle_plan_control_message(self, chat_id, text):
                            return
                        await self._send_chat_text(chat_id, RUNNING_REPLY)
                        return
                    plan_request = self._parse_plan_request(text)
                    if plan_request is not None:
                        await self._handle_plan_message(
                            chat_id, plan_request[0], plan_request[1], open_id or chat_id
                        )
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                    if text.startswith("/"):
                        await self._handle_slash_command(chat_id, message_id, text)
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                    if await self._menu_state.get_mode(open_id) == "plan_execute":
                        await self._handle_plan_message(chat_id, text, owner_id=open_id or chat_id)
                        logger.info(
                            "feishu_message_end",
                            chat_id=chat_id,
                            duration_ms=int((monotonic() - started_at) * 1000),
                        )
                        return
                    loop = await self._get_or_create_loop(chat_id, open_id or chat_id)
                    should_persist = True
                    result = await loop.run(text)
                    content = resolve_reply_text(result)
                    await self._persist_turn(chat_id, loop)
                    await self._reply_loop_result(loop, message_id, content)
                    await send_browse_web_artifacts(self, chat_id, loop)
                    logger.info(
                        "feishu_message_end",
                        chat_id=chat_id,
                        duration_ms=int((monotonic() - started_at) * 1000),
                    )
                except Exception:
                    if should_persist and loop is not None:
                        try:
                            await self._persist_turn(chat_id, loop)
                        except Exception:
                            logger.warning(
                                "feishu_message_persist_after_error_failed", chat_id=chat_id
                            )
                    logger.exception(
                        "feishu_message_error",
                        event_id=event_id,
                        chat_id=chat_id,
                        message_id=message_id,
                    )
                    try:
                        await self._reply(
                            message_id,
                            json.dumps(
                                {"text": "处理消息时出错，请稍后重试。详情请查看服务端日志。"}
                            ),
                        )
                    except Exception:
                        pass

    async def _try_reply_card(
        self,
        loop: AgentLoop,
        message_id: str,
        agent_reply: str,
    ) -> bool:
        try:
            tool_names, tool_args = collect_tool_calls(loop)
            if not tool_names:
                return False

            scenario = self._card_registry.match_scenario(tool_names)
            if scenario is None:
                return False

            # Pick primary tool for formatter (first matched trigger tool)
            cfg = self._card_registry.get_scenario(scenario)
            if cfg is None:
                return False
            primary_tool = next(
                (t for t in cfg.trigger_tools if t in tool_names),
                next(iter(tool_names)),
            )

            provider = await self._resolve_provider(loop._config.provider)
            formatter = CardFormatter(await self._pm.get_adapter(provider.id), loop._config.model)
            variables = await formatter.format(
                scenario,
                agent_reply,
                primary_tool,
                tool_args.get(primary_tool, {}),
                self._card_registry,
            )
            card_content = build_card_content(scenario, variables, self._card_registry)
            await self._reply(message_id, card_content, msg_type="interactive")
            return True
        except FeishuCardError:
            logger.warning("feishu_card_render_failed", message_id=message_id)
            return False
        except Exception:
            logger.exception("feishu_card_render_error", message_id=message_id)
            return False

    async def _get_or_create_loop(self, chat_id: str, owner_id: str = "") -> AgentLoop:
        session = await self._store.get(chat_id)
        provider = await self._resolve_provider(
            session.config.provider if session is not None else None
        )
        resolved_model = resolve_session_model(session, provider)
        loop = self._sessions.get(chat_id)
        if loop is None or loop._config.provider != provider.id:
            loop = await build_agent_loop(
                await self._pm.get_adapter(provider.id),
                session_id=chat_id,
                model=resolved_model,
                provider=provider.id,
                system_prompt=session.config.system_prompt if session is not None else None,
                agent_runtime=self._agent_runtime,
                spec_registry=self._spec_registry,
                task_queue=self._task_queue,
                owner_id=owner_id or chat_id,
            )
            attach_feishu_loop_approval(self, chat_id, loop)
            self._sessions[chat_id] = loop
        if session is None:
            loop.message_history.restore([])
            return loop
        self._restore_loop(loop, session, provider.id, resolved_model)
        return loop

    async def _handle_slash_command(self, chat_id: str, message_id: str, text: str) -> None:
        spec_id, input_text = parse_slash_command(text)
        if self._agent_runtime is None or self._spec_registry is None:
            await self._reply(message_id, json.dumps({"text": "场景运行时未初始化，请稍后重试。"}))
            return
        spec = self._spec_registry.get(spec_id)
        if not spec_id or spec is None or not spec.enabled:
            available_specs = self._available_specs_text()
            await self._reply(
                message_id,
                json.dumps(
                    {"text": f"未找到场景：{spec_id or '/'}，可用场景：{available_specs}"},
                    ensure_ascii=False,
                ),
            )
            return
        loop = await self._agent_runtime.create_loop_from_id(
            spec_id,
            session_id=f"feishu-slash:{chat_id}:{message_id}",
            task_queue=self._task_queue,
        )
        result = await loop.run(input_text)
        content = resolve_reply_text(result)
        await self._reply_loop_result(loop, message_id, content)

    async def _reply_loop_result(self, loop: AgentLoop, message_id: str, content: str) -> None:
        if await self._try_reply_card(loop, message_id, content):
            return
        for chunk in split_feishu_reply_text(content):
            await self._reply(message_id, json.dumps({"text": chunk}, ensure_ascii=False))

    def _available_specs_text(self) -> str:
        if self._spec_registry is None:
            return "无"
        return ", ".join(spec.id for spec in self._spec_registry.list_all()) or "无"

    async def _persist_turn(self, chat_id: str, loop: AgentLoop) -> None:
        try:
            await self._store.ensure_session(
                chat_id,
                model=loop._config.model,
                provider=loop._config.provider,
                system_prompt=loop._config.system_prompt,
                max_tokens=16384,
                title="飞书对话",
            )
            await self._store.save_messages(chat_id, _messages_without_system(loop.messages))
        except Exception:
            logger.warning("feishu_message_persist_failed", chat_id=chat_id)

    async def _record_outbound_text(
        self,
        chat_id: str,
        text: str,
        source: str = "feishu_outbound_text",
    ) -> None:
        try:
            await FeishuSessionRecorder(self._store).record_text(
                FeishuOutboundTextRecord(
                    chat_id=chat_id,
                    text=text,
                    source=source,
                    config=self._record_config(chat_id),
                )
            )
        except FeishuSessionRecorderError as exc:
            logger.warning("feishu_outbound_record_failed", chat_id=chat_id, error=str(exc))

    async def _record_outbound_file(self, record: FeishuOutboundFileRecord) -> None:
        try:
            await FeishuSessionRecorder(self._store).record_file(
                record.model_copy(update={"config": self._record_config(record.chat_id)})
            )
        except FeishuSessionRecorderError as exc:
            logger.warning(
                "feishu_outbound_file_record_failed",
                chat_id=record.chat_id,
                error=str(exc),
            )

    def _record_config(self, chat_id: str) -> FeishuRecordConfig:
        loop = self._sessions.get(chat_id)
        if loop is None:
            return FeishuRecordConfig()
        return FeishuRecordConfig(
            model=loop._config.model,
            provider=loop._config.provider,
            system_prompt=loop._config.system_prompt,
        )

    def _chat_lock(self, chat_id: str) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
        return lock

    @staticmethod
    def _restore_loop(
        loop: AgentLoop, session: Session, provider_id: str, resolved_model: str
    ) -> None:
        system_prompt = session.config.system_prompt or loop._config.system_prompt
        loop._config.model = resolved_model or loop._config.model
        loop._config.provider = provider_id
        loop._config.system_prompt = system_prompt
        loop.message_history.restore(
            restore_messages(session.messages, system_prompt) if session.messages else []
        )

    async def _seen(self, event_id: str) -> bool:
        return await self._deduplicator.seen(event_id)

    async def _reply(self, message_id: str, content: str, msg_type: str = "text") -> None:
        try:
            await self._client.reply_message(message_id, content, msg_type=msg_type)
            logger.info("feishu_reply_sent", message_id=message_id, msg_type=msg_type)
            await incr("feishu_replies")
        except Exception as exc:
            logger.exception(
                "feishu_reply_error", message_id=message_id, msg_type=msg_type, error=str(exc)
            )
            raise

    async def _send_chat_text(self, chat_id: str, text: str) -> None:
        await send_chat_text(self, chat_id, text)

    @staticmethod
    def _parse_plan_request(text: str) -> tuple[str, str] | None:
        return parse_plan_request(text)

    async def _resolve_provider(self, provider_key: str | None = None) -> Any:
        providers = await self._pm.list_all()
        if not providers:
            raise RuntimeError("No provider configured")
        for provider in providers:
            if provider_key and provider.id == provider_key:
                return provider
            if provider_key and provider.provider_type.value == provider_key:
                return provider
        return next((provider for provider in providers if provider.is_default), providers[0])


_extract_text = extract_text


def _messages_without_system(messages: list[Message]) -> list[Message]:
    return [message for message in messages if message.role != "system"]


__all__ = ["FeishuMessageHandler", "_extract_text"]
