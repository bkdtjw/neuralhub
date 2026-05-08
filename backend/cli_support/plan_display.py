from __future__ import annotations

import shutil
import sys

from backend.cli_support.plan_display_support import StepState, build_frame_lines, status_icon
from backend.core.s01_agent_loop.plan_models import ExecutionPlan, TodoState
from backend.core.s01_agent_loop.plan_renderer import SilentPlanRenderer


class CliPlanRenderError(Exception):
    pass


class CliPlanRenderer(SilentPlanRenderer):
    def __init__(self, ansi: bool = True) -> None:
        super().__init__()
        self._ansi = ansi
        self._plan_name = ""
        self._step_states: list[StepState] = []
        self._frame_height = 0
        self._scroll_region_set = False

    def _setup_scroll_region(self, status_label: str = "") -> None:
        if not self._ansi:
            return
        if not sys.stdout.isatty():
            self._ansi = False
            return
        rows = shutil.get_terminal_size().lines
        new_height = len(self._build_frame_lines(status_label))
        scroll_bottom = rows - new_height
        if scroll_bottom < 5:
            if self._scroll_region_set:
                self._restore_scroll_region(move_to_bottom=False)
            self._ansi = False
            return
        if self._scroll_region_set and self._frame_height == new_height:
            return
        if self._scroll_region_set:
            self._restore_scroll_region(move_to_bottom=False)
        self._frame_height = new_height
        sys.stdout.write(f"\033[1;{scroll_bottom}r")
        sys.stdout.write(f"\033[{scroll_bottom};1H")
        sys.stdout.flush()
        self._scroll_region_set = True

    def _teardown_scroll_region(self) -> None:
        if self._scroll_region_set:
            self._restore_scroll_region(move_to_bottom=True)

    def _restore_scroll_region(self, move_to_bottom: bool) -> None:
        rows = shutil.get_terminal_size().lines
        sys.stdout.write("\033[r")
        if move_to_bottom:
            sys.stdout.write(f"\033[{rows};1H\n")
        sys.stdout.flush()
        self._scroll_region_set = False

    def _render_fixed_frame(self, status_label: str = "") -> None:
        if not self._ansi:
            print("\n".join(self._build_frame_lines(status_label)))
            return
        self._setup_scroll_region(status_label)
        if not self._ansi:
            print("\n".join(self._build_frame_lines(status_label)))
            return
        rows = shutil.get_terminal_size().lines
        cols = shutil.get_terminal_size().columns
        frame_start_row = rows - self._frame_height + 1
        sys.stdout.write("\033[s")
        for index, line in enumerate(self._build_frame_lines(status_label)):
            row = frame_start_row + index
            sys.stdout.write(f"\033[{row};1H\033[K{line[:cols]}")
        sys.stdout.write("\033[u")
        sys.stdout.flush()

    def _build_frame_lines(self, status_label: str = "") -> list[str]:
        return build_frame_lines(self._plan_name, self._step_states, status_label)

    def _update_step(self, step_id: int, title: str | None = None, **kwargs: str) -> None:
        for step in self._step_states:
            if step.step_id == step_id:
                if title:
                    step.title = title
                for key, value in kwargs.items():
                    setattr(step, key, value)
                return
        self._step_states.append(StepState(step_id=step_id, title=title or f"step {step_id}"))
        self._step_states.sort(key=lambda step: step.step_id)
        self._update_step(step_id, title, **kwargs)

    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
        try:
            await super().on_plan_created(plan, plan_name)
            self._plan_name = plan_name
            self._step_states = [
                StepState(step_id=step.step_id, title=step.title) for step in plan.steps
            ]
            self._setup_scroll_region()
            self._render_fixed_frame()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_plan_approved(self, plan_name: str) -> None:
        try:
            await super().on_plan_approved(plan_name)
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
        try:
            await super().on_step_start(step_id, title, total_steps)
            self._update_step(step_id, title, status="⏳", detail="执行中...")
            self._render_fixed_frame()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_step_done(
        self,
        step_id: int,
        title: str,
        duration_s: float,
        output_summary: str,
    ) -> None:
        try:
            await super().on_step_done(step_id, title, duration_s, output_summary)
            self._update_step(step_id, title, status="✅", detail=f"({duration_s:.1f}s)")
            self._render_fixed_frame()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_step_failed(self, step_id: int, title: str, error: str) -> None:
        try:
            await super().on_step_failed(step_id, title, error)
            self._update_step(step_id, title, status="❌", detail=error[:30])
            self._render_fixed_frame()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_steps_updated(
        self,
        plan_name: str,
        steps: list[dict],
        todo_steps: list[dict],
    ) -> None:
        try:
            await super().on_steps_updated(plan_name, steps, todo_steps)
            self._step_states = [
                StepState(
                    int(step.get("id", 0)),
                    str(step.get("title", "")),
                    status_icon(str(step.get("status", "pending"))),
                )
                for step in todo_steps
            ]
            self._render_fixed_frame(status_label="已更新")
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None:
        try:
            await super().on_plan_completed(plan_name, todo_state)
            self._render_fixed_frame(status_label="完成")
            self._teardown_scroll_region()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_plan_partial_failed(
        self,
        plan_name: str,
        todo_state: TodoState,
        done: int,
        failed: int,
    ) -> None:
        try:
            await super().on_plan_partial_failed(plan_name, todo_state, done, failed)
            self._render_fixed_frame(status_label=f"部分失败 {done}/{done + failed}")
            self._teardown_scroll_region()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc

    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
        try:
            await super().on_plan_cancelled(plan_name, todo_state)
            for step in self._step_states:
                if step.status in {"⬜", "⏳"}:
                    step.detail = "已跳过"
            self._render_fixed_frame(status_label="已取消")
            self._teardown_scroll_region()
        except Exception as exc:
            raise CliPlanRenderError(str(exc)) from exc


__all__ = ["CliPlanRenderError", "CliPlanRenderer"]
