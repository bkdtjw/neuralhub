from __future__ import annotations

from typing import Protocol

from backend.core.task_queue_types import TaskPayload


class TaskPersistence(Protocol):
    async def save_payload(self, payload: TaskPayload) -> None: ...

    async def claim(self, task_id: str, worker_id: str) -> TaskPayload | None: ...

    async def complete(
        self,
        task_id: str,
        result: dict[str, object],
        worker_id: str = "",
    ) -> bool: ...

    async def fail(self, task_id: str, error: str, worker_id: str = "") -> bool: ...

    async def get_status(self, task_id: str) -> TaskPayload | None: ...

    async def list_task_ids(self) -> list[str]: ...

    async def list_stale_running(self, now: float) -> list[TaskPayload]: ...

    async def renew_lease(self, task_id: str, extension_seconds: float) -> None: ...

    async def has_checkpoint(self, task_id: str) -> bool: ...

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]: ...


__all__ = ["TaskPersistence"]
