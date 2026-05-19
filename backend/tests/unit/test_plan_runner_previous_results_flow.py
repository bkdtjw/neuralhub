from __future__ import annotations

import pytest

from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStore, TodoStore
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


def _runner(tmp_path, adapter: MockAdapter) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


@pytest.mark.asyncio
async def test_plan_runner_passes_previous_result_key_data_to_next_step(tmp_path) -> None:
    adapter = MockAdapter(
        [
            "recon",
            plan_json(step_count=2),
            'step1 done\n```json\n{"item_id": "X"}\n```',
            "step2 done",
        ]
    )
    runner = _runner(tmp_path, adapter)

    await run_with_approval(runner, "test")

    second_prompt = "\n".join(message.content for message in adapter.requests[3].messages)
    assert "item_id: 'X'" in second_prompt
