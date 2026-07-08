from __future__ import annotations

import json
from time import time

from sqlalchemy import select

from backend.common.errors import AgentError
from backend.core.task_queue_types import TaskPayload, TaskStatus
from backend.storage.database import SessionFactory, get_db_session
from backend.storage.models import MessageRecord, SubAgentTaskRecord
from backend.storage.sub_agent_task_codec import apply_payload, to_payload, to_record


class SubAgentTaskStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def save_payload(self, payload: TaskPayload) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(SubAgentTaskRecord, payload.task_id)
                if row is None:
                    db.add(to_record(payload))
                else:
                    apply_payload(row, payload)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_SAVE_ERROR", str(exc)) from exc

    async def claim(self, task_id: str, worker_id: str) -> TaskPayload | None:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = (
                    select(SubAgentTaskRecord)
                    .where(
                        SubAgentTaskRecord.id == task_id,
                        SubAgentTaskRecord.status == TaskStatus.PENDING.value,
                    )
                    .with_for_update(skip_locked=True)
                )
                row = (await db.execute(statement)).scalar_one_or_none()
                if row is None:
                    return None
                now = time()
                row.status = TaskStatus.RUNNING.value
                row.worker_id = worker_id
                row.started_at = now
                row.lease_expires_at = now + row.timeout_seconds
                await db.commit()
                await db.refresh(row)
                return to_payload(row)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_CLAIM_ERROR", str(exc)) from exc

    async def complete(
        self,
        task_id: str,
        result: dict[str, object],
        worker_id: str = "",
    ) -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(SubAgentTaskRecord, task_id)
                if row is None or row.status != TaskStatus.RUNNING.value:
                    return False
                if worker_id and row.worker_id != worker_id:
                    return False
                row.status = TaskStatus.SUCCEEDED.value
                row.result_json = json.dumps(result, ensure_ascii=False)
                row.error = ""
                await db.commit()
                return True
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_COMPLETE_ERROR", str(exc)) from exc

    async def fail(self, task_id: str, error: str, worker_id: str = "") -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(SubAgentTaskRecord, task_id)
                if row is None or row.status != TaskStatus.RUNNING.value:
                    return False
                if worker_id and row.worker_id != worker_id:
                    return False
                row.status = TaskStatus.FAILED.value
                row.error = error
                await db.commit()
                return True
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_FAIL_ERROR", str(exc)) from exc

    async def get_status(self, task_id: str) -> TaskPayload | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(SubAgentTaskRecord, task_id)
                return None if row is None else to_payload(row)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_STATUS_ERROR", str(exc)) from exc

    async def list_task_ids(self) -> list[str]:
        try:
            async with get_db_session(self._session_factory) as db:
                rows = await db.execute(select(SubAgentTaskRecord.id))
                return [str(row_id) for row_id in rows.scalars().all()]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_LIST_ERROR", str(exc)) from exc

    async def list_stale_running(self, now: float) -> list[TaskPayload]:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(SubAgentTaskRecord).where(
                    SubAgentTaskRecord.status == TaskStatus.RUNNING.value,
                    SubAgentTaskRecord.lease_expires_at > 0,
                    SubAgentTaskRecord.lease_expires_at < now,
                )
                rows = (await db.execute(statement)).scalars().all()
                return [to_payload(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_LIST_STALE_ERROR", str(exc)) from exc

    async def renew_lease(self, task_id: str, extension_seconds: float) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(SubAgentTaskRecord, task_id)
                if row is None or row.status != TaskStatus.RUNNING.value:
                    return
                row.lease_expires_at = time() + extension_seconds
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_RENEW_LEASE_ERROR", str(exc)) from exc

    async def has_checkpoint(self, task_id: str) -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = (
                    select(MessageRecord.id)
                    .where(MessageRecord.session_id == f"sub-agent:{task_id}")
                    .limit(1)
                )
                return (await db.execute(statement)).scalar_one_or_none() is not None
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_CHECKPOINT_ERROR", str(exc)) from exc

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]:
        if not parent_task_id:
            return []
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(SubAgentTaskRecord).where(
                    SubAgentTaskRecord.parent_task_id == parent_task_id,
                    SubAgentTaskRecord.status.in_(
                        [TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value]
                    ),
                )
                rows = (await db.execute(statement)).scalars().all()
                return [to_payload(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SUB_AGENT_TASK_CHILDREN_ERROR", str(exc)) from exc


__all__ = ["SubAgentTaskStore"]
