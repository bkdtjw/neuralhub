from __future__ import annotations

from backend.common.types import Message
from backend.core.s01_agent_loop.plan_execution_support import extract_step_context
from backend.core.s01_agent_loop.plan_models import PlanStep, TodoStep
from backend.core.s01_agent_loop.step_result import StepStatus


class FakeLoop:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages


def test_extract_step_context_returns_result_and_keeps_todo_fields() -> None:
    content = 'result_summary\n```json\n{"count": 12}\n```'
    todo_step = TodoStep(id=1, title="collect", status="done")
    plan_step = PlanStep(step_id=1, title="collect", description="Collect data")
    result = extract_step_context(
        todo_step,
        plan_step,
        FakeLoop([Message(role="assistant", content=content)]),
        "request-1",
    )

    assert result.status == StepStatus.DONE
    assert result.key_data == {"count": 12}
    assert result.result_summary == content
    assert todo_step.output_summary == content
