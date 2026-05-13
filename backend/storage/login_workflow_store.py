from __future__ import annotations

import json
import secrets
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.common.errors import AgentError
from backend.storage.database import SessionFactory, get_db_session
from backend.storage.models import LoginWorkflowRecord


class LoginStatus(StrEnum):
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFYING = "VERIFYING"
    FRESH = "FRESH"
    SKIPPED = "SKIPPED"


class SiteLoginState(BaseModel):
    site_id: str
    user_id: str
    status: LoginStatus = LoginStatus.EXPIRED
    last_check_at: datetime | None = None
    last_fresh_at: datetime | None = None
    workflow_id: str = ""
    current_step: int = 0
    total_steps: int = 0
    payload_json: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)


class LoginWorkflowStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def upsert(self, state: SiteLoginState) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(LoginWorkflowRecord, (state.user_id, state.site_id))
                if row is None:
                    db.add(_to_record(state))
                else:
                    _copy_state(row, state)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("LOGIN_WORKFLOW_UPSERT_ERROR", str(exc)) from exc

    async def get(self, user_id: str, site_id: str) -> SiteLoginState | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(LoginWorkflowRecord, (user_id, site_id))
                return _to_model(row) if row is not None else None
        except Exception as exc:  # noqa: BLE001
            raise AgentError("LOGIN_WORKFLOW_GET_ERROR", str(exc)) from exc

    async def list_by_status(
        self,
        user_id: str,
        statuses: list[LoginStatus],
    ) -> list[SiteLoginState]:
        try:
            values = [str(status) for status in statuses]
            statement = (
                select(LoginWorkflowRecord)
                .where(LoginWorkflowRecord.user_id == user_id)
                .where(LoginWorkflowRecord.status.in_(values))
                .order_by(LoginWorkflowRecord.current_step, LoginWorkflowRecord.site_id)
            )
            async with get_db_session(self._session_factory) as db:
                rows = (await db.execute(statement)).scalars().all()
                return [_to_model(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("LOGIN_WORKFLOW_LIST_ERROR", str(exc)) from exc

    async def create_workflow(self, user_id: str, sites: list[str]) -> str:
        try:
            active = await self._active_workflow(user_id)
            if active:
                return active
            workflow_id = f"login_{secrets.token_hex(8)}"
            total = len(sites)
            for index, site_id in enumerate(sites, start=1):
                await self.upsert(
                    SiteLoginState(
                        site_id=site_id,
                        user_id=user_id,
                        status=LoginStatus.PENDING,
                        workflow_id=workflow_id,
                        current_step=index,
                        total_steps=total,
                    )
                )
            return workflow_id
        except Exception as exc:  # noqa: BLE001
            raise AgentError("LOGIN_WORKFLOW_CREATE_ERROR", str(exc)) from exc

    async def advance(self, workflow_id: str) -> SiteLoginState | None:
        try:
            async with get_db_session(self._session_factory) as db:
                rows = (
                    await db.execute(
                        select(LoginWorkflowRecord)
                        .where(LoginWorkflowRecord.workflow_id == workflow_id)
                        .order_by(LoginWorkflowRecord.current_step)
                    )
                ).scalars().all()
                active = next((row for row in rows if row.status == LoginStatus.IN_PROGRESS), None)
                target = active or next(
                    (row for row in rows if row.status == LoginStatus.PENDING),
                    None,
                )
                if target is None:
                    return None
                target.status = LoginStatus.IN_PROGRESS
                target.updated_at = datetime.now()
                await db.commit()
                return _to_model(target)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("LOGIN_WORKFLOW_ADVANCE_ERROR", str(exc)) from exc

    async def _active_workflow(self, user_id: str) -> str:
        states = await self.list_by_status(user_id, [LoginStatus.PENDING, LoginStatus.IN_PROGRESS])
        return states[0].workflow_id if states else ""


def _to_record(state: SiteLoginState) -> LoginWorkflowRecord:
    return LoginWorkflowRecord(**_record_kwargs(state))


def _copy_state(row: LoginWorkflowRecord, state: SiteLoginState) -> None:
    for key, value in _record_kwargs(state).items():
        setattr(row, key, value)


def _record_kwargs(state: SiteLoginState) -> dict[str, Any]:
    return {
        "site_id": state.site_id,
        "user_id": state.user_id,
        "status": str(state.status),
        "last_check_at": state.last_check_at,
        "last_fresh_at": state.last_fresh_at,
        "workflow_id": state.workflow_id,
        "current_step": state.current_step,
        "total_steps": state.total_steps,
        "payload_json": json.dumps(state.payload_json, ensure_ascii=False),
        "updated_at": state.updated_at,
    }


def _to_model(row: LoginWorkflowRecord) -> SiteLoginState:
    return SiteLoginState(
        site_id=row.site_id,
        user_id=row.user_id,
        status=LoginStatus(row.status),
        last_check_at=row.last_check_at,
        last_fresh_at=row.last_fresh_at,
        workflow_id=row.workflow_id,
        current_step=row.current_step,
        total_steps=row.total_steps,
        payload_json=json.loads(row.payload_json or "{}"),
        updated_at=row.updated_at,
    )


__all__ = ["LoginStatus", "LoginWorkflowStore", "SiteLoginState"]
