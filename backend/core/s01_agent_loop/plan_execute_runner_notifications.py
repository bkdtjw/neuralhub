from __future__ import annotations

from typing import Any

from backend.common.logging import get_logger

logger = get_logger(component="plan_execute_runner")


class PlanExecuteRunnerNotificationsMixin:
    _plan_name: str
    _renderer: Any
    _todo_state: Any

    async def _notify_renderer(self, method_name: str, *args: object, **kwargs: object) -> None:
        if self._renderer is None:
            return
        try:
            method = getattr(self._renderer, method_name)
            await method(*args, **kwargs)
        except Exception:
            logger.warning("plan_renderer_error", method=method_name, plan_name=self._plan_name)

    async def _notify_finished(self) -> None:
        if self._todo_state is None:
            return
        if self._todo_state.status == "cancelled":
            await self._notify_renderer("on_plan_cancelled", self._plan_name, self._todo_state)
            return
        if self._todo_state.status == "partial_failed":
            done = 0
            failed = 0
            for step in self._todo_state.steps:
                done += 1 if step.status == "done" else 0
                failed += 1 if step.status == "failed" else 0
            await self._notify_renderer(
                "on_plan_partial_failed",
                self._plan_name,
                self._todo_state,
                done,
                failed,
            )
            return
        await self._notify_renderer("on_plan_completed", self._plan_name, self._todo_state)


__all__ = ["PlanExecuteRunnerNotificationsMixin"]
