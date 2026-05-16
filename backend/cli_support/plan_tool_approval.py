from __future__ import annotations

import asyncio

from backend.core.s01_agent_loop import PlanExecuteRunner

from .display import CliPrinter


def attach_cli_tool_approval(runner: PlanExecuteRunner, printer: CliPrinter) -> None:
    if not hasattr(runner, "_build_step_loop"):
        return
    original_build = runner._build_step_loop

    def build_step_loop(todo_step: object, context: object) -> object:
        loop = original_build(todo_step, context)

        async def on_event(event: object) -> None:
            if getattr(event, "type", "") == "tool_approval_required":
                await _prompt_cli_tool_approval(loop, getattr(event, "data", {}), printer)

        loop.on(on_event)
        return loop

    runner._build_step_loop = build_step_loop


async def _prompt_cli_tool_approval(loop: object, data: object, printer: CliPrinter) -> None:
    if not isinstance(data, dict):
        return
    for call in data.get("tool_calls", []):
        if not isinstance(call, dict):
            continue
        tool_call_id = str(call.get("id", ""))
        printer.print_info(f"[tool] {call.get('name')} 需要确认: {call.get('arguments')}")
        answer = await asyncio.to_thread(input, "approve tool? y/n: ")
        if answer.strip().lower() in {"y", "yes"}:
            loop.approve_tool_call(tool_call_id)
        else:
            loop.reject_tool_call(tool_call_id)


__all__ = ["attach_cli_tool_approval"]
