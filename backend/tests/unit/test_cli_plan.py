from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from backend.adapters.base import LLMAdapter
from backend.adapters.provider_manager import ProviderManager
from backend.cli_support import (
    CliPrinter,
    CliSession,
    CliState,
    parse_command,
    plan_commands,
)
from backend.cli_support.console_helpers import HELP_TEXT
from backend.cli_support.plan_commands import (
    handle_plan_show,
    handle_plans_list,
)
from backend.cli_support.plan_display import CliPlanRenderer
from backend.common.types import AgentConfig
from backend.core.s01_agent_loop import (
    AgentLoop,
    ExecutionPlan,
    PlanCheckpointStore,
    PlanPhase,
    PlanRenderer,
    PlanState,
    PlanStep,
    PlanStore,
    TodoState,
    TodoStore,
)
from backend.core.s02_tools import ToolRegistry
from backend.core.s05_skills import AgentRuntime
from backend.tests.unit.plan_execute_test_support import MockAdapter


class FakeProviderManager(ProviderManager):
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter

    async def get_adapter(self, provider_id: str | None = None) -> LLMAdapter:
        return self._adapter


class FakeStdout:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        self.parts.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True

    def text(self) -> str:
        return "".join(self.parts)


class FakeRuntime(AgentRuntime):
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter

    async def create_runner(self, **kwargs: object) -> object:
        renderer = cast("PlanRenderer | None", kwargs.get("renderer"))
        return plan_commands.PlanExecuteRunner(
            adapter=self._adapter,
            tool_registry=ToolRegistry(),
            plan_store=PlanStore(),
            todo_store=TodoStore(),
            renderer=renderer,
            session_id=str(kwargs.get("session_id", "")),
            owner_id=str(kwargs.get("owner_id", "unknown")),
        )


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        goal="test goal", steps=[PlanStep(step_id=1, title="step1", description="do step1")]
    )


def _todo(status: str = "completed") -> TodoState:
    return TodoState(plan_name="test-plan", session_id="cli", status=status)


def _printer() -> CliPrinter:
    printer = CliPrinter()
    printer._ansi = False  # noqa: SLF001
    return printer


def _session(adapter: LLMAdapter | None = None) -> CliSession:
    resolved = adapter or MockAdapter()
    registry = ToolRegistry()
    return CliSession(
        manager=FakeProviderManager(resolved),
        loop=AgentLoop(config=AgentConfig(model="test"), adapter=resolved, tool_registry=registry),
        registry=registry,
        state=CliState(
            provider_id="provider-1",
            provider_name="Provider",
            model="test",
            workspace="/tmp",
            permission_mode="auto",
        ),
        agent_runtime=FakeRuntime(resolved),
    )

@pytest.mark.asyncio
async def test_cli_renderer_frame_and_step_updates(capsys: pytest.CaptureFixture[str]) -> None:
    renderer = CliPlanRenderer(ansi=False)
    await renderer.on_plan_created(_plan(), "test-plan")
    await renderer.on_step_done(1, "step1", 3.2, "ok")
    output = capsys.readouterr().out
    assert "test-plan" in output
    assert "⬜" in output
    assert "✅" in output
    assert "3.2" in output
    assert "step1" in output

@pytest.mark.asyncio
async def test_cli_renderer_cancel_and_completed(capsys: pytest.CaptureFixture[str]) -> None:
    cancelled = CliPlanRenderer(ansi=False)
    await cancelled.on_plan_created(_plan(), "cancel-plan")
    await cancelled.on_plan_cancelled("cancel-plan", _todo("cancelled"))
    completed = CliPlanRenderer(ansi=False)
    await completed.on_plan_created(_plan(), "done-plan")
    await completed.on_plan_completed("done-plan", _todo())
    output = capsys.readouterr().out
    assert "已取消" in output
    assert "已跳过" in output
    assert "完成" in output


@pytest.mark.asyncio
async def test_cli_renderer_scroll_region_setup_and_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = FakeStdout()
    monkeypatch.setattr("backend.cli_support.plan_display.sys.stdout", stdout)
    monkeypatch.setattr(
        "backend.cli_support.plan_display.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    renderer = CliPlanRenderer(ansi=True)
    await renderer.on_plan_created(_plan(), "ansi-plan")
    renderer._teardown_scroll_region()  # noqa: SLF001
    output = stdout.text()
    assert all(item in output for item in ["\033[1;", "\033[s", "\033[u", "\033[r"])


def test_parse_plan_commands_and_help_text() -> None:
    assert parse_command("/plan 重构 s07").name == "/plan"
    assert parse_command("/plan 重构 s07").argument == "重构 s07"
    assert parse_command("/plans").name == "/plans"
    assert (
        parse_command("/plan show cosmic-plotting-bunny").argument == "show cosmic-plotting-bunny"
    )
    assert "/plan" in HELP_TEXT
    assert "/plans" in HELP_TEXT


@pytest.mark.asyncio
async def test_plans_list_and_plan_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    PlanCheckpointStore().save(
        PlanState(
            plan_name="test-plan",
            session_id="cli",
            phase=PlanPhase.COMPLETED,
            plan=_plan(),
        )
    )
    session = _session()
    await handle_plans_list(session, _printer())
    await handle_plan_show(session, "test-plan", _printer())
    output = capsys.readouterr().out
    assert all(item in output for item in ["test-plan", "test goal", "step1"])
