from __future__ import annotations

from pathlib import Path

import pytest

from backend.cli_support import handle_command, parse_command, plan_commands
from backend.cli_support.plan_commands import CliPlanCommandError, handle_plan_run
from backend.common.types import Message
from backend.tests.unit.plan_execute_test_support import MockAdapter
from backend.tests.unit.test_cli_plan import _printer, _session


@pytest.mark.asyncio
async def test_handle_plan_command_writes_files_and_injects_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    session = _session(MockAdapter())
    result = await handle_command(session, parse_command("/plan 重构 s07"), _printer())
    messages = result.session.loop.messages
    assert result.should_exit is False
    assert list((tmp_path / "data" / "plans").glob("*.md"))
    assert list((tmp_path / "data" / "plan_checkpoints").glob("*.json"))
    assert [message.role for message in messages[-2:]] == ["user", "assistant"]
    assert "Plan:" in messages[-1].content


@pytest.mark.asyncio
async def test_handle_plan_command_rejects_from_cli_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", fake_input)
    adapter = MockAdapter()
    session = _session(adapter)

    result = await handle_plan_run(session, "reject this", _printer())

    assert result.should_exit is False
    assert prompts and "是否执行此计划" in prompts[0]
    assert len(adapter.requests) == 1
    assert "cancelled" in result.session.loop.messages[-1].content


@pytest.mark.asyncio
async def test_plan_cancel_restores_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    class CancelRunner:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(self, message: str) -> Message:
            return self.build_exit_summary()

        def build_exit_summary(self) -> Message:
            return Message(role="assistant", content="Plan: cancel-plan\nStatus: cancelled")

    monkeypatch.setattr(plan_commands, "PlanExecuteRunner", CancelRunner)
    session = _session(MockAdapter())
    result = await handle_plan_run(session, "cancel", _printer())
    follow_up = await result.session.loop.run("next")
    assert result.should_exit is False
    assert "cancel-plan" in result.session.loop.messages[-3].content
    assert follow_up.role == "assistant"


@pytest.mark.asyncio
async def test_plan_run_exception_tears_down_scroll_region(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingRunner:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(self, message: str) -> Message:
            raise RuntimeError("boom")

        def build_exit_summary(self) -> Message:
            return Message(role="assistant", content="Plan: failed")

    class TeardownRenderer:
        def __init__(self, ansi: bool = True) -> None:
            self.calls = 0

        def _teardown_scroll_region(self) -> None:
            self.calls += 1

    renderer = TeardownRenderer()
    monkeypatch.setattr(plan_commands, "CliPlanRenderer", lambda ansi=True: renderer)
    monkeypatch.setattr(plan_commands, "PlanExecuteRunner", FailingRunner)
    with pytest.raises(CliPlanCommandError):
        await handle_plan_run(_session(MockAdapter()), "fail", _printer())
    assert renderer.calls == 1
