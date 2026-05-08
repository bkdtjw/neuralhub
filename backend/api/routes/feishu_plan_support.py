from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.common.logging import get_logger
from backend.core.s01_agent_loop import PlanControlStore, PlanExecuteRunner

from .feishu_plan_control import RUNNING_REPLY
from .feishu_plan_renderer import FeishuPlanRenderer
from .feishu_plan_runtime import FeishuPlanRunnerInput, create_feishu_plan_runner

logger = get_logger(component="feishu_handler")


async def handle_plan_message(handler: Any, chat_id: str, message_text: str, spec_id: str) -> None:
    try:
        if chat_id in handler._plan_runners:
            await send_chat_text(handler, chat_id, RUNNING_REPLY)
            return
        plan_input = message_text.strip() or (f"执行场景 {spec_id}" if spec_id else "")
        if not plan_input:
            await send_chat_text(handler, chat_id, "请在 /plan 后提供任务描述。")
            return
        PlanControlStore().clear(f"feishu-{chat_id}")
        renderer = FeishuPlanRenderer(handler._client, chat_id)
        runner = await create_feishu_plan_runner(
            FeishuPlanRunnerInput(
                provider_manager=handler._pm,
                chat_id=chat_id,
                renderer=renderer,
                agent_runtime=handler._agent_runtime,
                spec_id=spec_id,
                task_queue=handler._task_queue,
            )
        )
        handler._plan_runners[chat_id] = runner
        asyncio.create_task(handler._run_plan(chat_id, runner, plan_input))
    except Exception:
        logger.exception("feishu_plan_start_failed", chat_id=chat_id, spec_id=spec_id)
        await send_chat_text(handler, chat_id, "启动计划执行失败，请稍后重试。")


async def run_plan(handler: Any, chat_id: str, runner: PlanExecuteRunner, message: str) -> None:
    try:
        await runner.run(message)
        summary = _plan_result_text(runner)
        handler._plan_summaries[chat_id] = summary
        await send_chat_text(handler, chat_id, summary[:4000])
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("feishu_plan_run_failed", chat_id=chat_id)
        await send_chat_text(handler, chat_id, "计划执行失败，请查看服务端日志。")
    finally:
        if handler._plan_runners.get(chat_id) is runner:
            handler._plan_runners.pop(chat_id, None)
        try:
            handler._plan_summaries[chat_id] = runner.build_exit_summary().content
        except Exception:
            pass


async def send_chat_text(handler: Any, chat_id: str, text: str) -> None:
    await handler._client.send_message(chat_id, json.dumps({"text": text}, ensure_ascii=False))


def _plan_result_text(runner: PlanExecuteRunner) -> str:
    todo_state = getattr(runner, "_todo_state", None)
    if todo_state is not None:
        if any(getattr(step, "status", "") != "done" for step in getattr(todo_state, "steps", [])):
            return runner.build_exit_summary().content
        for step in reversed(getattr(todo_state, "steps", [])):
            output_summary = str(getattr(step, "output_summary", "")).strip()
            if getattr(step, "status", "") == "done" and output_summary:
                return output_summary
    return runner.build_exit_summary().content


def parse_plan_request(text: str) -> tuple[str, str] | None:
    if text.startswith("/plan "):
        return text[6:].strip(), ""
    if text.startswith("/") and "--plan" in text:
        command, plan_input = text.split("--plan", 1)
        spec_id = command.strip().lstrip("/").split(maxsplit=1)[0]
        return plan_input.strip(), spec_id
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict) and payload.get("mode") == "plan_execute":
        return (
            str(payload.get("message") or payload.get("text") or "").strip(),
            str(payload.get("spec_id") or ""),
        )
    return None


__all__ = ["handle_plan_message", "parse_plan_request", "run_plan", "send_chat_text"]
