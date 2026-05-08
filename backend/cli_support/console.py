from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from backend.common.errors import AgentError, LLMError

from .console_helpers import (
    HELP_TEXT,
    _find_model_owner,
    _find_provider,
    _format_provider_lines,
    _read_multiline_input,
)
from .display import CliPrinter
from .models import CliArgs, CliCommand, CliCommandResult, CliError, CliSession, SessionUpdate
from .plan_commands import handle_plan_run, handle_plan_show, handle_plans_list
from .session import rebuild_session, run_request


def parse_args(argv: Sequence[str] | None = None) -> CliArgs:
    parser = argparse.ArgumentParser(prog="miniclaude", description="Agent Studio CLI")
    parser.add_argument("-w", "--workspace", default=os.getcwd(), help="workspace path")
    parser.add_argument("-m", "--model", default=None, help="model name")
    parser.add_argument("-p", "--provider", default=None, help="provider id or name")
    parser.add_argument("--mcp-config", default=None, help="path to MCP server config")
    parser.add_argument(
        "--permission-mode",
        choices=["readonly", "auto", "full"],
        default="auto",
        help="tool permission mode",
    )
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="用指定 spec 执行一次性任务")
    run_parser.add_argument("spec_id", help="Skill spec ID")
    run_parser.add_argument("--input", "-i", dest="input_text", default="", help="输入文本")
    run_parser.add_argument("-w", "--workspace", default=os.getcwd(), help="workspace path")
    run_parser.add_argument("-p", "--provider", default=None, help="provider id or name")
    run_parser.add_argument("--mcp-config", default=None, help="path to MCP server config")
    run_parser.add_argument(
        "--permission-mode",
        choices=["readonly", "auto", "full"],
        default="auto",
        help="tool permission mode",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    return CliArgs(
        command=str(getattr(namespace, "command", "") or ""),
        spec_id=str(getattr(namespace, "spec_id", "") or ""),
        input_text=str(getattr(namespace, "input_text", "") or ""),
        workspace=os.path.abspath(namespace.workspace),
        model=getattr(namespace, "model", None),
        provider=getattr(namespace, "provider", None),
        permission_mode=namespace.permission_mode,
        mcp_config=os.path.abspath(namespace.mcp_config) if namespace.mcp_config else None,
    )


def parse_command(raw_command: str) -> CliCommand:
    stripped = raw_command.strip()
    parts = stripped.split(maxsplit=1)
    return CliCommand(name=parts[0].lower(), argument=parts[1].strip() if len(parts) > 1 else "")


async def handle_command(
    session: CliSession, command: CliCommand, printer: CliPrinter
) -> CliCommandResult:
    try:
        if command.name in {"/exit", "/quit"}:
            printer.print_info("bye.")
            return CliCommandResult(session=session, should_exit=True)
        if command.name == "/help":
            printer.print_info(HELP_TEXT)
            return CliCommandResult(session=session)
        if command.name == "/tools":
            printer.print_tools(session)
            return CliCommandResult(session=session)
        if command.name == "/plan":
            if command.argument.startswith("show "):
                return await handle_plan_show(session, command.argument[5:].strip(), printer)
            if not command.argument.strip():
                printer.print_info("[error] 用法: /plan <任务描述>  或  /plan show <name>")
                return CliCommandResult(session=session)
            return await handle_plan_run(session, command.argument, printer)
        if command.name == "/plans":
            return await handle_plans_list(session, printer)
        if command.name == "/clear":
            session.loop.reset()
            printer.print_info("[info] 对话历史已清空。")
            return CliCommandResult(session=session)
        if command.name == "/provider":
            providers = await session.manager.list_all()
            if not command.argument:
                printer.print_info(_format_provider_lines(providers, session.state.provider_id))
                return CliCommandResult(session=session)
            target = _find_provider(providers, command.argument)
            if target is None:
                printer.print_info(f"[error] provider 不存在: {command.argument}")
                return CliCommandResult(session=session)
            if target.id == session.state.provider_id:
                printer.print_info(f"[info] 当前 provider 已是 {target.name}")
                return CliCommandResult(session=session)
            updated = await rebuild_session(
                session,
                SessionUpdate(
                    provider=target.id,
                    model=target.default_model,
                    preserve_history=True,
                    clear_provider_metadata=True,
                ),
            )
            printer.print_info(
                "\n".join(
                    [
                        f"[info] 已切换到 provider {target.name}",
                        f"       model: {updated.state.model}",
                        "       models: "
                        + ", ".join(target.available_models or [target.default_model]),
                        "       history: preserved, provider metadata cleared",
                    ]
                )
            )
            return CliCommandResult(session=updated)
        if command.name == "/model":
            if not command.argument:
                printer.print_info(f"[info] 当前模型: {session.state.model}")
                return CliCommandResult(session=session)
            providers = await session.manager.list_all()
            owner = _find_model_owner(providers, command.argument)
            if owner is not None and owner.id != session.state.provider_id:
                printer.print_info(
                    "\n".join(
                        [
                            "[!] 当前 provider 是 "
                            f"{session.state.provider_name}，模型 {command.argument} "
                            "不在其可用模型列表中。",
                            f"    请先用 /provider {owner.name} 切换到 {owner.name} provider。",
                        ]
                    )
                )
                return CliCommandResult(session=session)
            if (
                session.state.available_models
                and command.argument not in session.state.available_models
            ):
                printer.print_info(f"[error] 当前 provider 不支持模型: {command.argument}")
                return CliCommandResult(session=session)
            updated = await rebuild_session(
                session,
                SessionUpdate(model=command.argument, preserve_history=True),
            )
            printer.print_info(f"[info] 已切换到模型 {updated.state.model}，对话历史已保留。")
            return CliCommandResult(session=updated)
        if command.name == "/workspace":
            if not command.argument:
                printer.print_info(f"[info] 当前工作目录: {session.state.workspace}")
                return CliCommandResult(session=session)
            updated = await rebuild_session(
                session,
                SessionUpdate(workspace=command.argument.strip().strip("\"'")),
            )
            printer.print_info(
                f"[info] 已切换工作目录到 {updated.state.workspace}，对话历史已清空。"
            )
            return CliCommandResult(session=updated)
        if command.name == "/tasks":
            try:
                from backend.core.s07_task_system.store import TaskStore

                task_store = TaskStore()
                tasks = await task_store.list_tasks()
                if not tasks:
                    printer.print_info("[info] 当前没有定时任务。")
                    return CliCommandResult(session=session)
                if command.argument.startswith("run "):
                    task_id = command.argument[4:].strip()
                    task = await task_store.get_task(task_id)
                    if task is None:
                        printer.print_info(f"[error] 任务 {task_id} 不存在")
                        return CliCommandResult(session=session)
                    printer.print_info(f"[info] 正在执行任务 {task.name}...")
                    try:
                        from backend.adapters.provider_manager import ProviderManager
                        from backend.core.s02_tools.mcp import MCPServerManager
                        from backend.core.s07_task_system import (
                            TaskExecutionError,
                            TaskExecutor,
                            TaskExecutorDeps,
                        )

                        executor = TaskExecutor(
                            TaskExecutorDeps(
                                provider_manager=ProviderManager(),
                                mcp_manager=MCPServerManager(),
                                agent_runtime=session.agent_runtime,
                                task_queue=session.task_queue,
                            )
                        )
                        result = await executor.execute(task)
                        await task_store.update_run_status(task.id, "success", result[:500])
                        printer.print_info(f"[info] 任务执行完成：\n{result[:2000]}")
                    except TaskExecutionError as exc:
                        await task_store.update_run_status(
                            task.id, "error", (exc.output or exc.message)[:500]
                        )
                        printer.print_info(f"[error] 执行失败：{exc.message}")
                    except Exception as exc:
                        printer.print_info(f"[error] 执行失败：{exc}")
                    return CliCommandResult(session=session)
                lines = ["[info] 当前定时任务："]
                for i, t in enumerate(tasks, 1):
                    status = "启用" if t.enabled else "停用"
                    last = f" | 上次: {t.last_run_status}" if t.last_run_status else ""
                    lines.append(f"  {i}. [{t.id}] {t.name} | {t.cron} | {status}{last}")
                printer.print_info("\n".join(lines))
            except Exception as exc:
                printer.print_info(f"[error] 查询任务失败：{exc}")
            return CliCommandResult(session=session)
        printer.print_info("[error] 未知命令，输入 /help 查看可用命令。")
        return CliCommandResult(session=session)
    except (CliError, AgentError, LLMError):
        raise
    except Exception as exc:
        raise CliError("CLI_COMMAND_ERROR", str(exc)) from exc


async def run_repl(session: CliSession, printer: CliPrinter) -> None:
    try:
        current_session = session
        printer.print_welcome(current_session)
        while True:
            user_input = _read_multiline_input(printer)
            if user_input is None:
                printer.print_info("bye.")
                return
            if not user_input:
                continue
            if user_input.startswith("/"):
                result = await handle_command(current_session, parse_command(user_input), printer)
                current_session = result.session
                if result.should_exit:
                    return
                continue
            try:
                await run_request(current_session, user_input)
            except CliError as exc:
                printer.print_info(f"[error] {exc.message}")
            except (AgentError, LLMError):
                continue
    except (CliError, AgentError, LLMError):
        raise
    except Exception as exc:
        raise CliError("CLI_REPL_ERROR", str(exc)) from exc


__all__ = ["_read_multiline_input", "handle_command", "parse_args", "parse_command", "run_repl"]
