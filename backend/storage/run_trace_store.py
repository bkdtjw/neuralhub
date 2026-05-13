from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.common.errors import AgentError
from backend.storage.database import SessionFactory, get_db_session
from backend.storage.models import RunTraceRecord


def _trace_id() -> str:
    return f"trace_{secrets.token_hex(8)}"


class RunTrace(BaseModel):
    id: str = Field(default_factory=_trace_id)
    task_id: str = ""
    kind: str
    url: str = ""
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: datetime | None = None
    success: bool = False
    error_code: str = ""
    payload_json: dict[str, Any] = Field(default_factory=dict)


class RunTraceStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def record(self, trace: RunTrace) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                db.add(_to_record(trace))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("RUN_TRACE_RECORD_ERROR", str(exc)) from exc

    async def query(
        self,
        task_id: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RunTrace]:
        try:
            statement = select(RunTraceRecord).order_by(RunTraceRecord.started_at)
            if task_id:
                statement = statement.where(RunTraceRecord.task_id == task_id)
            if kind:
                statement = statement.where(RunTraceRecord.kind == kind)
            if since:
                statement = statement.where(RunTraceRecord.started_at >= since)
            if until:
                statement = statement.where(RunTraceRecord.started_at <= until)
            async with get_db_session(self._session_factory) as db:
                rows = (await db.execute(statement)).scalars().all()
                return [_to_model(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("RUN_TRACE_QUERY_ERROR", str(exc)) from exc


def _to_record(trace: RunTrace) -> RunTraceRecord:
    return RunTraceRecord(
        id=trace.id,
        task_id=trace.task_id,
        kind=trace.kind,
        url=trace.url,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        success=trace.success,
        error_code=trace.error_code,
        payload_json=json.dumps(trace.payload_json, ensure_ascii=False),
    )


def _to_model(row: RunTraceRecord) -> RunTrace:
    return RunTrace(
        id=row.id,
        task_id=row.task_id,
        kind=row.kind,
        url=row.url,
        started_at=row.started_at,
        ended_at=row.ended_at,
        success=row.success,
        error_code=row.error_code,
        payload_json=json.loads(row.payload_json or "{}"),
    )


__all__ = ["RunTrace", "RunTraceStore"]
