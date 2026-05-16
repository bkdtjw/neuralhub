from __future__ import annotations

import pytest

from backend.adapters.base import LLMAdapter
from backend.adapters.provider_manager import ProviderManager
from backend.cli_support import CliPrinter, CliSession, CliState
from backend.cli_support.plan_commands import handle_plan_run
from backend.common.types import AgentConfig
from backend.core.s01_agent_loop import (
    AgentLoop,
    ExecutionPlan,
    PlanCheckpointStore,
    PlanPhase,
    PlanState,
    PlanStep,
    TodoState,
    TodoStep,
)
from backend.core.s02_tools import ToolRegistry
from backend.core.s05_skills import AgentRuntime
from backend.tests.unit.plan_execute_test_support import MockAdapter


class FakeProviderManager(ProviderManager):
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter

    async def get_adapter(self, provider_id: str | None = None) -> LLMAdapter:
        return self._adapter


class ResumeOnlyRuntime(AgentRuntime):
    def __init__(self) -> None:
        pass

    async def create_runner(self, **kwargs: object) -> object:
        raise AssertionError("new plan runner should not be created")


def _printer() -> CliPrinter:
    printer = CliPrinter()
    printer._ansi = False  # noqa: SLF001
    return printer


@pytest.mark.asyncio
async def test_cli_plan_command_resumes_unfinished_checkpoint(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    adapter = MockAdapter(["resumed"])
    registry = ToolRegistry()
    session = CliSession(
        manager=FakeProviderManager(adapter),
        loop=AgentLoop(config=AgentConfig(model="test"), adapter=adapter, tool_registry=registry),
        registry=registry,
        state=CliState(
            provider_id="provider-1",
            provider_name="Provider",
            model="test",
            workspace="/tmp",
            permission_mode="auto",
        ),
        agent_runtime=ResumeOnlyRuntime(),  # type: ignore[arg-type]
    )
    plan = ExecutionPlan(
        goal="resume goal",
        steps=[PlanStep(step_id=1, title="resume step", description="do it")],
    )
    PlanCheckpointStore().save(
        PlanState(
            plan_name="resume-plan",
            session_id="cli",
            phase=PlanPhase.EXECUTING,
            plan=plan,
            todo=TodoState(
                plan_name="resume-plan",
                session_id="cli",
                status="executing",
                steps=[TodoStep(id=1, title="resume step", status="running")],
            ),
        )
    )

    result = await handle_plan_run(session, "new request should be ignored", _printer())

    assert result.should_exit is False
    assert adapter.requests
    assert result.session.loop.messages[-1].role == "assistant"
