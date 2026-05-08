from __future__ import annotations

import asyncio
import json

from backend.common.errors import AgentError
from backend.common.types import (
    LLMResponse,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStatus, PlanStore, TodoStore
from backend.core.s01_agent_loop.plan_execution_support import OUTPUT_SUMMARY_LIMIT
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json


def _runner(
    tmp_path,
    adapter: MockAdapter,
    registry: ToolRegistry | None = None,
) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=registry or ToolRegistry(),
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


def _tool_call_response(path: str = "backend/core/demo.py") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="tc1", name="read_path", arguments={"path": path}),
        ],
    )


def test_runner_executes_steps_with_agent_loop(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=2), "步骤1完成", "步骤2完成"])
    runner = _runner(tmp_path, adapter)
    asyncio.run(runner.run("test"))
    assert runner.status == PlanStatus.COMPLETED
    assert runner._todo_state is not None
    assert all(step.status == "done" for step in runner._todo_state.steps)
    assert all(step.duration_s > 0 for step in runner._todo_state.steps)


def test_extract_context_from_step(tmp_path) -> None:
    adapter = MockAdapter(
        ["侦察报告", plan_json(step_count=1), _tool_call_response(), "最终摘要" * 1200]
    )
    runner = _runner(tmp_path, adapter, _registry_with_reader())
    asyncio.run(runner.run("test"))
    step = runner._todo_state.steps[0]
    assert step.files_touched == ["backend/core/demo.py"]
    assert step.key_findings == ["关键发现第一行"]
    assert step.output_summary
    assert len(step.output_summary) == OUTPUT_SUMMARY_LIMIT


def test_step_context_passed_to_next_step(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=2), "FIRST_SUMMARY", "SECOND_SUMMARY"])
    runner = _runner(tmp_path, adapter)
    asyncio.run(runner.run("test"))
    second_step_prompt = "\n".join(message.content for message in adapter.requests[3].messages)
    assert "FIRST_SUMMARY" in second_step_prompt


def test_runner_step_failure_continues(tmp_path) -> None:
    adapter = MockAdapter(
        ["侦察报告", plan_json(step_count=3), "done1", AgentError("STEP_FAILED", "boom"), "done3"]
    )
    runner = _runner(tmp_path, adapter)
    asyncio.run(runner.run("test"))
    statuses = [step.status for step in runner._todo_state.steps]
    assert statuses == ["done", "failed", "done"]
    assert runner.status == PlanStatus.PARTIAL_FAILED
    summary = runner.build_exit_summary().content
    assert "❌ Step 2" in summary
    assert "boom" in summary


def test_runner_step_timeout(tmp_path, monkeypatch) -> None:
    import backend.core.s01_agent_loop.plan_execute_runner_steps as steps_module

    class TimeoutAdapter(MockAdapter):
        async def complete(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return LLMResponse(content="侦察报告")
            if len(self.requests) == 2:
                return LLMResponse(content=plan_json(step_count=2))
            if len(self.requests) == 3:
                await asyncio.sleep(0.02)
            return LLMResponse(content="done")

    monkeypatch.setattr(steps_module, "STEP_TIMEOUT_SECONDS", 0.01)
    runner = _runner(tmp_path, TimeoutAdapter())
    asyncio.run(runner.run("test"))
    assert [step.status for step in runner._todo_state.steps] == ["failed", "done"]
    assert runner._todo_state.steps[0].output_summary == "步骤执行超时"


def test_sync_rereads_plan_from_file(tmp_path) -> None:
    plan = json.dumps(
        {
            "goal": "sync",
            "approach": ["a"],
            "data_structures": "",
            "steps": [
                {"step_id": 1, "title": "s1", "description": "d1", "tools_hint": []},
                {"step_id": 2, "title": "s2", "description": "原始第二步描述", "tools_hint": []},
            ],
        },
        ensure_ascii=False,
    )
    adapter = MockAdapter(["侦察报告", plan, "done1", "done2"])
    runner = _runner(tmp_path, adapter)
    original_execute = runner._execute_step

    async def edit_plan_after_first(step) -> None:
        await original_execute(step)
        if step.id == 1:
            path = tmp_path / "plans" / f"{runner.plan_name}.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("原始第二步描述", "手动修改后的描述"),
                encoding="utf-8",
            )

    runner._execute_step = edit_plan_after_first
    asyncio.run(runner.run("test"))
    second_prompt = "\n".join(message.content for message in adapter.requests[3].messages)
    assert "手动修改后的描述" in second_prompt


def test_cancel_preserves_completed_context(tmp_path) -> None:
    adapter = MockAdapter(
        [
            "侦察报告",
            plan_json(step_count=3),
            _tool_call_response(),
            "step1 done",
            "step2 done",
        ]
    )
    runner = _runner(tmp_path, adapter, _registry_with_reader())
    original_execute = runner._execute_step

    async def cancel_after_second(step) -> None:
        await original_execute(step)
        if step.id == 2:
            runner.cancel()

    runner._execute_step = cancel_after_second
    asyncio.run(runner.run("test"))
    summary = runner.build_exit_summary().content
    assert "✅" in summary
    assert "⏭" in summary
    assert "backend/core/demo.py" in summary or "关键发现第一行" in summary
