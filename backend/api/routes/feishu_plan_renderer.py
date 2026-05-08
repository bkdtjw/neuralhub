from __future__ import annotations

from dataclasses import dataclass

from backend.core.s01_agent_loop.plan_models import ExecutionPlan, TodoState
from backend.core.s01_agent_loop.plan_renderer import SilentPlanRenderer
from backend.core.s02_tools.builtin.feishu_client import FeishuClient


@dataclass
class _StepState:
    step_id: int
    title: str
    status: str = "⬜"
    detail: str = ""


class FeishuPlanRenderer(SilentPlanRenderer):
    """Updates one Feishu interactive card through the plan lifecycle."""

    def __init__(self, feishu_client: FeishuClient, chat_id: str) -> None:
        super().__init__()
        self._client = feishu_client
        self._chat_id = chat_id
        self._message_id: str | None = None
        self._plan_name = ""
        self._step_states: list[_StepState] = []
        self._final = False
        self._final_template = ""

    @property
    def message_id(self) -> str | None:
        return self._message_id

    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
        await super().on_plan_created(plan, plan_name)
        self._plan_name = plan_name
        self._step_states = [
            _StepState(step_id=step.step_id, title=step.title) for step in plan.steps
        ]
        card = self._build_card(show_buttons=True, status_text="等待确认")
        self._message_id = await self._client.send_card(self._chat_id, card)

    async def on_plan_approved(self, plan_name: str) -> None:
        await super().on_plan_approved(plan_name)
        await self._update_card(show_buttons=False, status_text="执行中")

    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
        await super().on_step_start(step_id, title, total_steps)
        self._update_step(step_id, title=title, status="⏳", detail="执行中...")
        await self._update_card(show_buttons=False, status_text="执行中")

    async def on_step_done(
        self,
        step_id: int,
        title: str,
        duration_s: float,
        output_summary: str,
    ) -> None:
        await super().on_step_done(step_id, title, duration_s, output_summary)
        self._update_step(
            step_id,
            title=title,
            status="✅",
            detail=f"({duration_s:.1f}s)",
        )
        await self._update_card(show_buttons=False, status_text="执行中")

    async def on_step_failed(self, step_id: int, title: str, error: str) -> None:
        await super().on_step_failed(step_id, title, error)
        self._update_step(step_id, title=title, status="❌", detail=error[:30])
        await self._update_card(show_buttons=False, status_text="执行中")

    async def on_steps_updated(
        self,
        plan_name: str,
        steps: list[dict],
        todo_steps: list[dict],
    ) -> None:
        await super().on_steps_updated(plan_name, steps, todo_steps)
        self._step_states = [
            _StepState(
                step_id=int(step.get("id", 0)),
                title=str(step.get("title", "")),
                status=_status_icon(str(step.get("status", "pending"))),
            )
            for step in todo_steps
        ]
        await self._update_card(show_buttons=False, status_text="执行中 (计划已更新)")

    async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None:
        await super().on_plan_completed(plan_name, todo_state)
        self._final = True
        self._final_template = "green"
        done = sum(1 for step in self._step_states if step.status == "✅")
        await self._update_card(False, f"完成 ({done}/{len(self._step_states)})")

    async def on_plan_partial_failed(
        self,
        plan_name: str,
        todo_state: TodoState,
        done: int,
        failed: int,
    ) -> None:
        await super().on_plan_partial_failed(plan_name, todo_state, done, failed)
        self._final = True
        self._final_template = "orange"
        await self._update_card(False, f"部分失败 (完成 {done}，失败 {failed})")

    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
        await super().on_plan_cancelled(plan_name, todo_state)
        self._final = True
        self._final_template = "red"
        for step in self._step_states:
            if step.status in {"⬜", "⏳"}:
                step.detail = "已跳过"
        done = sum(1 for step in self._step_states if step.status == "✅")
        await self._update_card(False, f"已取消 ({done}/{len(self._step_states)})")

    def _update_step(self, step_id: int, title: str = "", **kwargs: str) -> None:
        for step in self._step_states:
            if step.step_id == step_id:
                if title:
                    step.title = title
                for key, value in kwargs.items():
                    setattr(step, key, value)
                return

    async def _update_card(self, show_buttons: bool, status_text: str) -> None:
        if self._message_id is None:
            return
        try:
            await self._client.update_card(
                self._message_id,
                self._build_card(show_buttons, status_text),
            )
        except Exception:
            return

    def _build_card(self, show_buttons: bool, status_text: str) -> dict:
        elements: list[dict] = [{"tag": "markdown", "content": self._steps_markdown()}]
        if show_buttons:
            elements.append({"tag": "action", "actions": self._action_buttons()})
        template = "blue"
        if self._final:
            template = self._final_template or "green"
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"📋 {self._plan_name}"},
                "subtitle": {"tag": "plain_text", "content": status_text},
                "template": template,
            },
            "elements": elements,
        }

    def _steps_markdown(self) -> str:
        lines: list[str] = []
        for step in self._step_states:
            detail = f" {step.detail}" if step.detail else ""
            lines.append(f"{step.status} **{step.title}**{detail}")
        return "\n".join(lines) or "暂无步骤"

    def _action_buttons(self) -> list[dict]:
        return [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 确认执行"},
                "type": "primary",
                "value": self._button_value("plan_approve"),
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "❌ 取消"},
                "type": "danger",
                "value": self._button_value("plan_cancel"),
            },
        ]

    def _button_value(self, action: str) -> dict[str, str]:
        return {
            "action": action,
            "action_type": action,
            "plan_name": self._plan_name,
            "chat_id": self._chat_id,
        }


def _status_icon(status: str) -> str:
    if status == "done":
        return "✅"
    if status == "failed":
        return "❌"
    if status == "running":
        return "⏳"
    return "⬜"


__all__ = ["FeishuPlanRenderer"]
