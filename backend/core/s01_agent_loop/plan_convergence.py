from __future__ import annotations

from backend.common.types import AgentEvent, Message

from .agent_loop import AgentLoop
from .plan_step_prompt import CONVERGENCE_PROMPTS, CONVERGENCE_THRESHOLDS


class ConvergenceMonitor:
    def __init__(self, loop: AgentLoop, step_goal: str) -> None:
        self._loop = loop
        self._step_goal = step_goal
        self._tool_call_count = 0
        self._injected_thresholds: set[int] = set()
        self._pending_prompts: list[str] = []

    def on_event(self, event: AgentEvent) -> None:
        if event.type == "tool_result":
            self._tool_call_count += 1
            self._queue_due_prompts()
            return
        if event.type == "status_change" and event.data == "thinking":
            self._flush_pending_prompts()

    def _queue_due_prompts(self) -> None:
        for threshold in CONVERGENCE_THRESHOLDS:
            if self._tool_call_count < threshold or threshold in self._injected_thresholds:
                continue
            self._injected_thresholds.add(threshold)
            self._pending_prompts.append(
                CONVERGENCE_PROMPTS[threshold].format(
                    n=self._tool_call_count,
                    step_goal=self._step_goal,
                )
            )

    def _flush_pending_prompts(self) -> None:
        self._loop.message_history.extend(
            [Message(role="user", content=prompt) for prompt in self._pending_prompts]
        )
        self._pending_prompts.clear()


__all__ = ["ConvergenceMonitor"]
