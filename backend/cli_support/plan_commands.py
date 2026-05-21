from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from backend.common.errors import AgentError
from backend.common.types import Message
from backend.core.s01_agent_loop import (
    PlanCheckpointStore,
    PlanExecuteRunner,
    PlanPhase,
    PlanState,
    PlanStore,
    TodoStore,
)
from backend.core.s01_agent_loop.plan_state_machine import TERMINAL_PHASES

from .display import CliPrinter
from .models import CliCommandResult, CliError, CliSession
from .plan_display import CliPlanRenderer
from .plan_tool_approval import attach_cli_tool_approval


class CliPlanCommandError(CliError):
    """Raised when a CLI plan command cannot be completed."""

async def _cli_approval_handler(runner: PlanExecuteRunner) -> None:
    try:
        approval_phases = {PlanPhase.CONFIRMING, PlanPhase.AWAITING_APPROVAL}
        stop_phases = {*approval_phases, PlanPhase.EXECUTING, *TERMINAL_PHASES}
        while getattr(runner, "phase", PlanPhase.EXECUTING) not in stop_phases:
            await asyncio.sleep(0.05)
        if getattr(runner, "phase", None) not in approval_phases:
            return
        answer = await asyncio.to_thread(input, "[plan] 是否执行此计划？(y/n): ")
        if answer.strip().lower() in {"", "y", "yes"}:
            runner.approve()
        else:
            runner.reject("用户拒绝")
    except asyncio.CancelledError:
        raise
    except (EOFError, KeyboardInterrupt):
        _reject_cli_approval(runner, "用户取消")
    except Exception as exc:  # noqa: BLE001
        _reject_cli_approval(runner, f"审批输入失败: {exc}")

def _reject_cli_approval(runner: PlanExecuteRunner, reason: str) -> None:
    reject = getattr(runner, "reject", None)
    if callable(reject):
        reject(reason)

async def handle_plan_run(
    session: CliSession,
    message: str,
    printer: CliPrinter,
) -> CliCommandResult:
    previous_handler = signal.getsignal(signal.SIGINT)
    interrupted = False
    renderer = CliPlanRenderer(ansi=bool(getattr(printer, "_ansi", False)))
    runner: PlanExecuteRunner | None = None
    approval_task: asyncio.Task[None] | None = None
    resumed = False

    try:
        if session.agent_runtime is None:
            raise CliPlanCommandError("CLI_PLAN_RUNTIME_MISSING", "agent runtime is not available")
        checkpoint_store = PlanCheckpointStore()
        existing = _latest_cli_checkpoint(checkpoint_store)
        if existing is not None:
            answer = await asyncio.to_thread(
                input,
                f"[plan] 发现未完成的计划「{existing.plan_name}」，继续？(y/n): ",
            )
            if answer.strip().lower() in {"y", "yes"}:
                adapter = await session.manager.get_adapter(session.state.provider_id)
                runner = PlanExecuteRunner.resume_from_checkpoint(
                    checkpoint_store,
                    "cli",
                    adapter,
                    session.registry,
                    PlanStore(),
                    TodoStore(),
                    renderer,
                    owner_id="cli_local",
                )
                resumed = runner is not None
            else:
                checkpoint_store.delete(existing.session_id, existing.plan_name)
        if runner is None:
            created = await session.agent_runtime.create_runner(
                mode="plan_execute",
                workspace=session.state.workspace,
                session_id="cli",
                model=session.state.model,
                provider=session.state.provider_id,
                renderer=renderer,
                task_queue=session.task_queue,
                event_handler=session.event_handler,
                owner_id="cli_local",
            )
            if not isinstance(created, PlanExecuteRunner):
                raise CliPlanCommandError(
                    "CLI_PLAN_RUNNER_TYPE_ERROR", "plan mode did not create runner"
                )
            runner = created
        attach_cli_tool_approval(runner, printer)

        def _handle_sigint(signum: int, frame: object | None) -> None:
            nonlocal interrupted
            _ = signum, frame
            if interrupted:
                return
            interrupted = True
            if runner is not None:
                runner.cancel()
            print("\n[interrupt] 正在取消计划...")
        signal.signal(signal.SIGINT, _handle_sigint)
        approval_task = asyncio.create_task(_cli_approval_handler(runner))
        try:
            if resumed:
                await runner.resume_run()
            else:
                await runner.run(message)
            if interrupted:
                printer.print_info("[info] 计划已取消。")
        except AgentError as exc:
            if interrupted and exc.code == "LOOP_ABORTED":
                printer.print_info("[info] 计划已取消。")
            else:
                printer.print_info(f"[error] {exc.message}")
        finally:
            if approval_task is not None and not approval_task.done():
                approval_task.cancel()
                with suppress(asyncio.CancelledError):
                    await approval_task
        return CliCommandResult(session=session)
    except (CliPlanCommandError, AgentError):
        raise
    except Exception as exc:
        raise CliPlanCommandError("CLI_PLAN_RUN_ERROR", str(exc)) from exc
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        try:
            renderer._teardown_scroll_region()  # noqa: SLF001
        except Exception:
            pass
        if runner is not None:
            summary = runner.build_exit_summary()
            messages = [summary] if resumed else [Message(role="user", content=message), summary]
            session.loop.message_history.extend(messages)

async def handle_plans_list(session: CliSession, printer: CliPrinter) -> CliCommandResult:
    try:
        plans = PlanCheckpointStore().list_checkpoints("cli")
        if not plans:
            printer.print_info("[info] 暂无历史计划。")
            return CliCommandResult(session=session)
        lines = ["[info] 历史计划：", *[f"  - {name}" for name in plans]]
        lines.append("\n  查看详情: /plan show <name>")
        printer.print_info("\n".join(lines))
        return CliCommandResult(session=session)
    except Exception as exc:
        raise CliPlanCommandError("CLI_PLAN_LIST_ERROR", str(exc)) from exc

def _latest_cli_checkpoint(checkpoint_store: PlanCheckpointStore) -> PlanState | None:
    states = [
        state
        for owner_id in ("cli_local", "unknown")
        for state in checkpoint_store.find_incomplete_by_owner(owner_id)
        if state.session_id == "cli"
    ]
    if not states:
        return None
    return max(states, key=lambda state: state.updated_at)

async def handle_plan_show(
    session: CliSession, plan_name: str, printer: CliPrinter
) -> CliCommandResult:
    try:
        state = PlanCheckpointStore().load("cli", plan_name)
        if state is None or state.plan is None:
            raise CliPlanCommandError("CLI_PLAN_NOT_FOUND", plan_name)
        plan = state.plan
        lines = [
            f"[plan] {plan_name}",
            f"  目标: {plan.goal}",
            f"  版本: v{plan.version}",
            f"  步骤: {len(plan.steps)} 步",
            "",
        ]
        for step in plan.steps:
            lines.append(f"  {step.step_id}. {step.title}")
            lines.append(f"     {step.description}")
        printer.print_info("\n".join(lines))
        return CliCommandResult(session=session)
    except Exception:
        printer.print_info(f"[error] 计划不存在: {plan_name}")
        return CliCommandResult(session=session)
__all__ = ["CliPlanCommandError", "handle_plan_run", "handle_plan_show", "handle_plans_list"]
