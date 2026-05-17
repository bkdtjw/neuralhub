from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    Message,
    StreamChunk,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanExecuteRunner,
    PlanStep,
    PlanStore,
    TodoState,
    TodoStep,
    TodoStore,
)
from backend.core.s01_agent_loop.agent_loop_support import build_llm_request
from backend.core.s01_agent_loop.plan_execution_support import StepContext
from backend.core.s02_tools import ToolRegistry


class MockAdapter(LLMAdapter):
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="done")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")

    async def test_connection(self) -> bool:
        return True


def _tool(name: str = "echo") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="search",
        parameters=ToolParameterSchema(),
    )


def test_dynamic_skill_messages_do_not_change_cache_prefix_hash() -> None:
    config = AgentConfig(model="model", provider="provider", system_prompt="stable")
    tools = [_tool()]

    first = build_llm_request(
        config,
        [Message(role="user", content="run")],
        tools,
        static_skill_messages=[Message(role="system", content="skill A")],
    )
    second = build_llm_request(
        config,
        [Message(role="user", content="run again")],
        tools,
        static_skill_messages=[Message(role="system", content="skill B")],
    )

    assert first.cache_prefix_hash == second.cache_prefix_hash
    assert first.skill_messages[0].content == "skill A"
    assert second.skill_messages[0].content == "skill B"


def test_plan_step_loop_keeps_step_prompt_in_zone2(tmp_path) -> None:
    runner = PlanExecuteRunner(
        MockAdapter(),
        ToolRegistry(),
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
        system_prompt="stable prefix",
        skill_prompt="spec skill",
    )
    plan_step = PlanStep(step_id=1, title="Step", description="Do it")
    todo_step = TodoStep(id=1, title="Step")
    context = StepContext(plan_step, "", 1, 1)

    loop = runner._build_step_loop(todo_step, context)  # noqa: SLF001
    request = build_llm_request(
        loop._config,  # noqa: SLF001
        [Message(role="user", content="go")],
        loop._executor.list_definitions(),  # noqa: SLF001
        static_skill_messages=loop._static_skill_messages,  # noqa: SLF001
    )

    assert request.system_prompt == "stable prefix"
    assert request.skill_messages[0].content == "spec skill"
    assert "计划执行者" in request.skill_messages[1].content


@pytest.mark.asyncio
async def test_script_step_runs_tool_without_agent_loop(tmp_path) -> None:
    async def echo(args: dict[str, object]) -> ToolResult:
        return ToolResult(output=f"script result: {args['value']}")

    registry = ToolRegistry()
    registry.register(_tool("echo"), echo)
    adapter = MockAdapter()
    runner = PlanExecuteRunner(
        adapter,
        registry,
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
        session_id="session",
    )
    plan_step = PlanStep(
        step_id=1,
        title="Run script",
        description="Call thick tool",
        type="script_step",
        tool_name="echo",
        tool_arguments={"value": "ok"},
    )
    runner._plan_name = "plan"  # noqa: SLF001
    runner._plan = ExecutionPlan(goal="g", steps=[plan_step])  # noqa: SLF001
    runner._todo_state = TodoState(  # noqa: SLF001
        plan_name="plan",
        session_id="session",
        steps=[TodoStep(id=1, title="Run script")],
    )

    await runner._execute_step(runner._todo_state.steps[0])  # noqa: SLF001

    assert adapter.requests == []
    assert runner._todo_state.steps[0].status == "done"  # noqa: SLF001
    assert "script result: ok" in runner._todo_state.steps[0].output_summary  # noqa: SLF001
    assert "完整步骤结果:" in runner._todo_state.steps[0].output_summary  # noqa: SLF001
    assert (tmp_path / "steps" / "step_1.json").exists()
