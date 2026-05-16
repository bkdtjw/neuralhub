from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from time import time

from backend.common.types import Message
from backend.core.s01_agent_loop import MessageHistory
from backend.core.s05_skills import AgentCategory, AgentSpec, SpecRegistry
from backend.core.task_queue import TaskQueue
from backend.core.task_queue_types import TaskPayload, TaskStatus


async def expired_running(
    queue: TaskQueue,
    task_id: str,
    input_data: dict[str, object],
    max_retries: int = 1,
) -> TaskPayload:
    await queue.submit(task_id, input_data, timeout_seconds=60, max_retries=max_retries)
    claimed = await queue.claim("worker-a")
    assert claimed is not None
    expired = claimed.model_copy(update={"lease_expires_at": time() - 1})
    await queue._save_payload(expired)  # noqa: SLF001
    return expired


async def status(queue: TaskQueue, task_id: str) -> TaskPayload:
    current = await queue.get_status(task_id)
    assert current is not None
    return current


class Loop:
    def __init__(self) -> None:
        self._config = SimpleNamespace(model="m", provider="p", system_prompt="s")
        self.message_history = MessageHistory()

    @property
    def messages(self) -> list[Message]:
        return self.message_history.messages


class Runtime:
    def __init__(self) -> None:
        self.loop = Loop()

    async def create_loop_from_id(self, *_args: Any, **_kwargs: Any) -> Loop:
        return self.loop

    async def create_loop_inline(self, *_args: Any, **_kwargs: Any) -> Loop:
        return self.loop


class ReuseQueue:
    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.child = TaskPayload(
            task_id="old-child",
            namespace="sub_agent",
            input_data={"spec_id": "code-reviewer", "parent_task_id": "parent-1"},
            parent_task_id="parent-1",
            status=TaskStatus.SUCCEEDED,
            created_at=0,
            result={"content": "old result"},
        )
        self.statuses = {"old-child": self.child}

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]:
        return [self.child] if parent_task_id == "parent-1" else []

    async def submit(
        self,
        task_id: str,
        input_data: dict[str, Any],
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
    ) -> TaskPayload:
        self.submitted.append(task_id)
        payload = TaskPayload(
            task_id=task_id,
            namespace="sub_agent",
            input_data=input_data,
            parent_task_id=str(input_data.get("parent_task_id", "")),
            status=TaskStatus.SUCCEEDED,
            created_at=0,
            timeout_seconds=timeout_seconds,
            result={"content": "new result"},
            max_retries=max_retries,
        )
        self.statuses[task_id] = payload
        return payload

    async def get_status(self, task_id: str) -> TaskPayload | None:
        return self.statuses.get(task_id)

    async def wait_for_tasks(
        self,
        task_ids: list[str],
        poll_interval: float = 0.5,
        global_timeout: float = 0.0,
    ) -> list[TaskPayload]:
        _ = poll_interval
        _ = global_timeout
        return [self.statuses[task_id] for task_id in task_ids]


def registry() -> SpecRegistry:
    items = SpecRegistry()
    items.register(
        AgentSpec(
            id="code-reviewer",
            title="Code Reviewer",
            category=AgentCategory.CODING,
            timeout_seconds=180,
        )
    )
    return items


__all__ = ["ReuseQueue", "Runtime", "expired_running", "registry", "status"]
