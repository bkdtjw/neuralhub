from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime

from backend.common.types import AgentEvent, Message, ToolCall, ToolResult

from .diff_rendering import render_file_diffs
from .formatting import (
    format_output,
    frame,
    group_tools,
    load_version,
    short_workspace,
    shorten,
    summarize_tools,
)
from .markdown import display_width, render_markdown, render_table
from .models import CliSession
from .spinner import SpinnerRenderer


def _thinking_label(model: str) -> str | None:
    lowered = model.lower()
    if "thinking" in lowered or lowered.endswith("-r1") or "reasoner" in lowered:
        return "auto"
    return None


class CliPrinter:
    def __init__(self) -> None:
        self._last_status = ""
        self._ansi = self._enable_ansi()
        self._renderer = SpinnerRenderer(ansi=self._ansi)
        self._version = load_version()

    def print_info(self, message: str) -> None:
        print(message)

    def print_welcome(self, session: CliSession) -> None:
        lines = [
            f"miniclaude v{self._version}",
            f"provider: {session.state.provider_name}  model: {session.state.model}",
            f"workspace: {short_workspace(session.state.workspace)}",
        ]
        thinking = _thinking_label(session.state.model)
        if thinking is not None:
            lines.append(f"thinking: {thinking}")
        print("")
        print(frame(lines))
        print("")
        self.print_tools(session)
        print("")
        print("  commands")
        print(
            "    /help  /clear  /provider <name>  /model <name>  "
            "/workspace <path>  /tools  /plan <message>  /plans  /exit"
        )
        print("")
        print(f"  {self._paint('tips: 空行提交 | Ctrl+C 中断 | Ctrl+D 退出', '90')}")
        print("")

    def print_tools(self, session: CliSession) -> None:
        definitions = session.registry.list_definitions()
        print(f"  tools ({len(definitions)})")
        for group, names in group_tools(definitions):
            print(f"    {group.ljust(9)} {summarize_tools(names)}")

    def prompt(self, multiline: bool = False) -> str:
        return "... " if multiline else self._paint("> ", "1;37")

    def handle_event(self, event: AgentEvent) -> None:
        if event.type == "status_change":
            self._handle_status(str(event.data))
            return
        if event.type == "tool_call" and isinstance(event.data, ToolCall):
            self._handle_tool_call(event.data, event.timestamp)
            return
        if event.type == "tool_result" and isinstance(event.data, ToolResult):
            self._handle_tool_result(event.data, event.timestamp)
            return
        if event.type == "security_reject" and isinstance(event.data, ToolResult):
            self._handle_security_reject(event.data)
            return
        if event.type == "message" and isinstance(event.data, Message):
            self._handle_message(event.data)
            return
        if event.type in {"sub_agent_spawned", "sub_agent_completed", "sub_agent_failed"}:
            self._handle_sub_agent_event(event.data)
            return
        if event.type == "error":
            self._handle_error(event.data)

    def _handle_status(self, status: str) -> None:
        if status == self._last_status:
            return
        self._last_status = status
        if status in {"thinking", "compacting"}:
            label = "思考中..." if status == "thinking" else "压缩上下文..."
            self._renderer.show_status(label)
            return
        self._renderer.clear_status()

    def _handle_tool_call(self, tool_call: ToolCall, timestamp: datetime) -> None:
        self._last_status = ""
        label = self._summarize_call(tool_call)
        self._renderer.start_tool(tool_call.id, label, timestamp)

    def _handle_tool_result(self, result: ToolResult, timestamp: datetime) -> None:
        self._last_status = ""
        preview = "\n".join(format_output(result.output or ""))
        self._renderer.finish_tool(result.tool_call_id, result.is_error, preview, timestamp)
        diff_text = render_file_diffs(result.diffs, self._paint)
        if diff_text:
            self._renderer.pause()
            try:
                print(diff_text)
            finally:
                self._renderer.resume()

    def _handle_security_reject(self, result: ToolResult) -> None:
        self._renderer.reject_tool(result.tool_call_id, result.output)

    def _handle_message(self, message: Message) -> None:
        content = message.content.strip()
        if message.role != "assistant" or not content:
            return
        self._last_status = ""
        self._renderer.pause()
        try:
            print(self._render_markdown(content))
        finally:
            self._renderer.resume()

    def _handle_error(self, error: object) -> None:
        if isinstance(error, asyncio.CancelledError):
            return
        self._renderer.clear_status()
        message = getattr(error, "message", str(error))
        if message:
            print(self._paint(f"[error] {message}", "31"))

    def _handle_sub_agent_event(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        message = str(data.get("message", "")).strip()
        if message:
            self._renderer.pause()
            try:
                print(self._paint(f"[sub-agent] {message}", "36"))
            finally:
                self._renderer.resume()

    def _summarize_call(self, tool_call: ToolCall) -> str:
        detail = tool_call.arguments.get("command") or tool_call.arguments.get("path")
        if not isinstance(detail, str) or not detail:
            detail = json.dumps(tool_call.arguments, ensure_ascii=False)
        return f"{tool_call.name}({shorten(detail, 80)})"

    def _enable_ansi(self) -> bool:
        if os.getenv("NO_COLOR") or not sys.stdout.isatty():
            return False
        if os.name != "nt":
            return True
        try:
            os.system("")
        except OSError:
            return False
        return True

    def _paint(self, text: str, code: str) -> str:
        if not self._ansi:
            return text
        return f"\033[{code}m{text}\033[0m"

    def _render_markdown(self, text: str) -> str:
        return render_markdown(text, self._ansi, self._paint)

    def _display_width(self, text: str) -> int:
        return display_width(text)

    def _render_table(self, lines: list[str]) -> str:
        return render_table(lines, self._ansi)


__all__ = ["CliPrinter"]
