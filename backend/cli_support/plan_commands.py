from __future__ import annotations

import signal

from backend.common.errors import AgentError
from backend.common.types import Message
from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStore

from .display import CliPrinter
from .models import CliCommandResult, CliError, CliSession
from .plan_display import CliPlanRenderer


class CliPlanCommandError(CliError):
    """Raised when a CLI plan command cannot be completed."""


async def handle_plan_run(
    session: CliSession,
    message: str,
    printer: CliPrinter,
) -> CliCommandResult:
    previous_handler = signal.getsignal(signal.SIGINT)
    interrupted = False
    renderer = CliPlanRenderer(ansi=bool(getattr(printer, "_ansi", False)))
    runner: PlanExecuteRunner | None = None

    try:
        if session.agent_runtime is None:
            raise CliPlanCommandError("CLI_PLAN_RUNTIME_MISSING", "agent runtime is not available")
        created = await session.agent_runtime.create_runner(
            mode="plan_execute",
            workspace=session.state.workspace,
            session_id="cli",
            model=session.state.model,
            provider=session.state.provider_id,
            renderer=renderer,
            task_queue=session.task_queue,
            event_handler=session.event_handler,
        )
        if not isinstance(created, PlanExecuteRunner):
            raise CliPlanCommandError(
                "CLI_PLAN_RUNNER_TYPE_ERROR", "plan mode did not create runner"
            )
        runner = created

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
        try:
            await runner.run(message)
            if interrupted:
                printer.print_info("[info] 计划已取消。")
        except AgentError as exc:
            if interrupted and exc.code == "LOOP_ABORTED":
                printer.print_info("[info] 计划已取消。")
            else:
                printer.print_info(f"[error] {exc.message}")
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
            user_msg = Message(role="user", content=message)
            session.loop._messages.extend([user_msg, summary])  # noqa: SLF001


async def handle_plans_list(session: CliSession, printer: CliPrinter) -> CliCommandResult:
    try:
        plans = PlanStore().list_plans()
        if not plans:
            printer.print_info("[info] 暂无历史计划。")
            return CliCommandResult(session=session)
        lines = ["[info] 历史计划：", *[f"  - {name}" for name in plans]]
        lines.append("\n  查看详情: /plan show <name>")
        printer.print_info("\n".join(lines))
        return CliCommandResult(session=session)
    except Exception as exc:
        raise CliPlanCommandError("CLI_PLAN_LIST_ERROR", str(exc)) from exc


async def handle_plan_show(
    session: CliSession, plan_name: str, printer: CliPrinter
) -> CliCommandResult:
    try:
        plan = PlanStore().read_plan(plan_name)
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
