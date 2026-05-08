from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.common.logging import get_logger

from .plan_models import ExecutionPlan, TodoState


@runtime_checkable
class PlanRenderer(Protocol):
    async def on_recon_start(self, goal: str) -> None: ...
    async def on_recon_done(self, report_preview: str) -> None: ...
    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None: ...
    async def on_plan_approved(self, plan_name: str) -> None: ...
    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None: ...
    async def on_step_done(
        self,
        step_id: int,
        title: str,
        duration_s: float,
        output_summary: str,
    ) -> None: ...
    async def on_step_failed(self, step_id: int, title: str, error: str) -> None: ...
    async def on_amendment(
        self,
        plan_name: str,
        version: int,
        reason: str,
        amended_step_count: int,
    ) -> None: ...
    async def on_steps_updated(
        self,
        plan_name: str,
        steps: list[dict],
        todo_steps: list[dict],
    ) -> None: ...
    async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None: ...
    async def on_plan_partial_failed(
        self,
        plan_name: str,
        todo_state: TodoState,
        done: int,
        failed: int,
    ) -> None: ...
    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None: ...


class SilentPlanRenderer:
    def __init__(self) -> None:
        self._logger = get_logger(component="plan_renderer")

    async def on_recon_start(self, goal: str) -> None:
        self._logger.info("plan_recon_start", goal=goal[:200])

    async def on_recon_done(self, report_preview: str) -> None:
        self._logger.info("plan_recon_done", report_preview=report_preview[:200])

    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
        self._logger.info("plan_created", plan_name=plan_name, step_count=len(plan.steps))

    async def on_plan_approved(self, plan_name: str) -> None:
        self._logger.info("plan_approved", plan_name=plan_name)

    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
        self._logger.info("plan_step_start", step_id=step_id, title=title, total=total_steps)

    async def on_step_done(
        self,
        step_id: int,
        title: str,
        duration_s: float,
        output_summary: str,
    ) -> None:
        self._logger.info(
            "plan_step_done", step_id=step_id, title=title, duration_s=round(duration_s, 1)
        )

    async def on_step_failed(self, step_id: int, title: str, error: str) -> None:
        self._logger.warning("plan_step_failed", step_id=step_id, title=title, error=error[:200])

    async def on_amendment(
        self,
        plan_name: str,
        version: int,
        reason: str,
        amended_step_count: int,
    ) -> None:
        self._logger.info(
            "plan_amended",
            plan_name=plan_name,
            version=version,
            reason=reason[:200],
            amended_step_count=amended_step_count,
        )

    async def on_steps_updated(
        self,
        plan_name: str,
        steps: list[dict],
        todo_steps: list[dict],
    ) -> None:
        self._logger.info(
            "plan_steps_updated",
            plan_name=plan_name,
            step_count=len(steps),
            todo_step_count=len(todo_steps),
        )

    async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None:
        done = sum(1 for step in todo_state.steps if step.status == "done")
        self._logger.info(
            "plan_completed", plan_name=plan_name, done=done, total=len(todo_state.steps)
        )

    async def on_plan_partial_failed(
        self,
        plan_name: str,
        todo_state: TodoState,
        done: int,
        failed: int,
    ) -> None:
        self._logger.warning(
            "plan_partial_failed",
            plan_name=plan_name,
            done=done,
            failed=failed,
            total=len(todo_state.steps),
        )

    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
        done = sum(1 for step in todo_state.steps if step.status == "done")
        self._logger.info(
            "plan_cancelled", plan_name=plan_name, done=done, total=len(todo_state.steps)
        )


__all__ = ["PlanRenderer", "SilentPlanRenderer"]
