from __future__ import annotations

from backend.core.s01_agent_loop.plan_execution_support import build_step_context
from backend.core.s01_agent_loop.plan_models import ExecutionPlan, PlanStep, TodoState, TodoStep
from backend.core.s01_agent_loop.step_result import StepResult, StepStatus


def _result(step_id: int, summary: str, key_data: dict[str, object]) -> StepResult:
    return StepResult(
        step_id=step_id,
        request_id=f"request-{step_id}",
        status=StepStatus.DONE,
        task=f"step {step_id}",
        result_summary=summary,
        key_data=key_data,
    )


def test_step_context_carries_previous_results() -> None:
    plan = ExecutionPlan(
        goal="goal",
        steps=[
            PlanStep(step_id=1, title="one", description="d1"),
            PlanStep(step_id=2, title="two", description="d2"),
            PlanStep(step_id=3, title="three", description="d3"),
        ],
    )
    todo = TodoState(plan_name="p", session_id="s", steps=[TodoStep(id=3, title="three")])
    previous_results = [
        _result(1, "first summary", {"count": 1}),
        _result(2, "second summary", {"count": 2}),
    ]

    context = build_step_context(plan, todo, todo.steps[0], previous_results)

    assert context is not None
    assert len(context.previous_results) == 2
    assert context.previous_results[1].key_data == {"count": 2}
    assert context.previous_summary == "second summary"
