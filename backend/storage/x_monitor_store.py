from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.common.errors import AgentError

from .database import SessionFactory, get_db_session
from .x_monitor_models import XMonitor, XMonitorHit, XMonitorHitRecord, XMonitorRecord

_MONITOR_FIELDS = (
    "query", "interval_minutes", "days_window", "search_type",
    "threshold_likes", "threshold_views", "enabled",
)


def _to_monitor(row: XMonitorRecord) -> XMonitor:
    return XMonitor(**{name: getattr(row, name) for name in XMonitor.model_fields})


def _to_hit(row: XMonitorHitRecord) -> XMonitorHit:
    return XMonitorHit(**{name: getattr(row, name) for name in XMonitorHit.model_fields})


class XMonitorStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def create_monitor(self, fields: dict[str, Any]) -> XMonitor:
        try:
            async with get_db_session(self._session_factory) as db:
                row = XMonitorRecord(
                    id=uuid4().hex,
                    created_at=datetime.utcnow(),
                    **{name: fields[name] for name in _MONITOR_FIELDS if name in fields},
                )
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return _to_monitor(row)
        except Exception as exc:
            raise AgentError("X_MONITOR_CREATE_ERROR", str(exc)) from exc

    async def list_monitors(self) -> list[XMonitor]:
        try:
            async with get_db_session(self._session_factory) as db:
                rows = (
                    await db.execute(select(XMonitorRecord).order_by(XMonitorRecord.created_at))
                ).scalars().all()
                return [_to_monitor(row) for row in rows]
        except Exception as exc:
            raise AgentError("X_MONITOR_LIST_ERROR", str(exc)) from exc

    async def get_monitor(self, monitor_id: str) -> XMonitor | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(XMonitorRecord, monitor_id)
                return _to_monitor(row) if row else None
        except Exception as exc:
            raise AgentError("X_MONITOR_GET_ERROR", str(exc)) from exc

    async def update_monitor(self, monitor_id: str, fields: dict[str, Any]) -> XMonitor | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(XMonitorRecord, monitor_id)
                if row is None:
                    return None
                for name in _MONITOR_FIELDS:
                    if name in fields and fields[name] is not None:
                        setattr(row, name, fields[name])
                await db.commit()
                await db.refresh(row)
                return _to_monitor(row)
        except Exception as exc:
            raise AgentError("X_MONITOR_UPDATE_ERROR", str(exc)) from exc

    async def delete_monitor(self, monitor_id: str) -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                result = await db.execute(
                    delete(XMonitorRecord).where(XMonitorRecord.id == monitor_id)
                )
                await db.commit()
                return bool(result.rowcount)
        except Exception as exc:
            raise AgentError("X_MONITOR_DELETE_ERROR", str(exc)) from exc

    async def count_monitors(self) -> int:
        try:
            return len(await self.list_monitors())
        except AgentError:
            raise

    async def list_due(self, now: datetime) -> list[XMonitor]:
        # 到期 = 启用 且（从未跑过 或 上次运行 + 间隔 ≤ now）。行数≤上限(默认20)，取回后内存过滤即可。
        try:
            monitors = await self.list_monitors()
            return [
                monitor for monitor in monitors
                if monitor.enabled
                and (
                    monitor.last_run_at is None
                    or monitor.last_run_at + timedelta(minutes=monitor.interval_minutes) <= now
                )
            ]
        except AgentError:
            raise

    async def mark_run(self, monitor_id: str, status: str, now: datetime) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(XMonitorRecord, monitor_id)
                if row is None:
                    return
                row.last_run_at = now
                row.last_status = status[:20]
                await db.commit()
        except Exception as exc:
            raise AgentError("X_MONITOR_MARK_RUN_ERROR", str(exc)) from exc

    async def insert_hit(self, fields: dict[str, Any]) -> str | None:
        """新命中返回 hit id；(monitor_id, tweet_url) 已存在返回 None（同推文只记/只报一次）。"""
        try:
            async with get_db_session(self._session_factory) as db:
                hit_id = uuid4().hex
                statement = (
                    pg_insert(XMonitorHitRecord)
                    .values(id=hit_id, created_at=datetime.utcnow(), notified=False, **fields)
                    .on_conflict_do_nothing(constraint="uq_x_monitor_hit")
                )
                result = await db.execute(statement)
                await db.commit()
                return hit_id if result.rowcount else None
        except Exception as exc:
            raise AgentError("X_MONITOR_HIT_INSERT_ERROR", str(exc)) from exc

    async def list_hits(self, monitor_id: str, limit: int = 50) -> list[XMonitorHit]:
        try:
            async with get_db_session(self._session_factory) as db:
                rows = (
                    await db.execute(
                        select(XMonitorHitRecord)
                        .where(XMonitorHitRecord.monitor_id == monitor_id)
                        .order_by(XMonitorHitRecord.created_at.desc())
                        .limit(limit)
                    )
                ).scalars().all()
                return [_to_hit(row) for row in rows]
        except Exception as exc:
            raise AgentError("X_MONITOR_HIT_LIST_ERROR", str(exc)) from exc

    async def set_hit_notified(self, hit_id: str, notified: bool) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(XMonitorHitRecord, hit_id)
                if row is None:
                    return
                row.notified = notified
                await db.commit()
        except Exception as exc:
            raise AgentError("X_MONITOR_HIT_NOTIFY_ERROR", str(exc)) from exc


__all__ = ["XMonitorStore"]
