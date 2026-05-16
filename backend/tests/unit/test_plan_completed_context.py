from __future__ import annotations

import pytest
from backend.common.types import (
    LLMResponse,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s01_agent_loop import (
    PlanExecuteRunner,
    PlanStep,
    PlanStore,
    TodoState,
    TodoStep,
    TodoStore,
)
from backend.core.s01_agent_loop.plan_execution_support import (
    StepContext,
    build_completed_steps_context,
)
from backend.core.s01_agent_loop.plan_step_prompt import build_step_messages
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


def _runner(tmp_path, adapter: MockAdapter, registry: ToolRegistry) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=registry,
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


def _registry_with_reader() -> ToolRegistry:
    async def read_path(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="关键发现第一行\nsecond line")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read_path",
            description="read",
            category="file-ops",
            parameters=ToolParameterSchema(),
        ),
        read_path,
    )
    return registry


def _tool_call_response(path: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id="tc1", name="read_path", arguments={"path": path})],
    )


@pytest.mark.asyncio
async def test_completed_steps_context_injected_into_later_step_prompts(tmp_path) -> None:
    adapter = MockAdapter(
        [
            "侦察报告",
            plan_json(step_count=4),
            _tool_call_response("backend/core/first.py"),
            "步骤1完成",
            _tool_call_response("backend/core/second.py"),
            "步骤2完成",
            "步骤3完成",
            "步骤4完成",
        ]
    )
    runner = _runner(tmp_path, adapter, _registry_with_reader())
    await run_with_approval(runner, "test")
    first_prompt = "\n".join(message.content for message in adapter.requests[2].messages)
    third_prompt = "\n".join(message.content for message in adapter.requests[6].messages)
    fourth_prompt = "\n".join(message.content for message in adapter.requests[7].messages)

    assert "已完成步骤上下文" not in first_prompt
    assert "### 步骤 1: 步骤1" in third_prompt
    assert "### 步骤 2: 步骤2" in third_prompt
    assert "backend/core/first.py" in third_prompt
    assert "backend/core/second.py" in third_prompt
    assert "### 步骤 3: 步骤3" in fourth_prompt
    assert "修改文件: 无" in fourth_prompt


def test_build_completed_steps_context_degrades_older_steps() -> None:
    steps = [
        TodoStep(
            id=index,
            title=f"步骤{index}",
            status="done",
            output_summary="摘要" * 200,
            files_touched=[f"file{index}.py"],
            key_findings=[f"发现{index}-{finding}" for finding in range(7)],
        )
        for index in range(1, 9)
    ]
    state = TodoState(plan_name="p", session_id="s", steps=steps)
    context = build_completed_steps_context(state, 9)

    assert build_completed_steps_context(None, 1) == ""
    assert len(context) <= 2000
    assert "步骤 1: 步骤1 | 文件: file1.py" in context
    assert "### 步骤 1" not in context
    assert "### 步骤 6: 步骤6" in context
    assert "发现6-4" in context
    assert "发现6-5" not in context


def test_step_context_and_step_messages_default_compatibility() -> None:
    step = PlanStep(step_id=1, title="t", description="d")
    context = StepContext(step, "prev", 1, 1)

    assert context.completed_context == ""
    assert build_step_messages(step, 1, 1, "prev") == build_step_messages(step, 1, 1, "prev", "")
    assert "已完成步骤上下文" not in build_step_messages(step, 1, 1, "prev")[0]
