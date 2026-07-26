from __future__ import annotations

import uuid
from inspect import isawaitable
from typing import Any, Literal

from backend.common.logging import get_logger
from backend.common.types import AgentEvent, AgentEventHandler

from .transcript_store import SubAgentTranscriptStore, get_sub_agent_transcript_store

logger = get_logger(component="sub_agent_progress")

ProgressSource = Literal["orchestrate", "dispatch"]

_PREVIEW_LIMIT = 160
_CHILD_FORWARD_TYPES = {"tool_call", "tool_result", "message"}


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def clip_preview(text: object, limit: int = _PREVIEW_LIMIT) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


class SubAgentProgressEmitter:
    """把子 agent 运行进度转发给父会话的事件通道。

    进度是尽力而为的旁路：handler 缺失时全部为 no-op，handler 抛错只记日志，
    绝不影响编排/派发主流程。
    """

    def __init__(
        self,
        handler: AgentEventHandler | None,
        source: ProgressSource,
        run_id: str | None = None,
        store: SubAgentTranscriptStore | None = None,
    ) -> None:
        self._handler = handler
        self._source = source
        self.run_id = run_id or new_run_id()
        self._store = store if store is not None else get_sub_agent_transcript_store()

    def _record(self, action: Any) -> None:
        try:
            action(self._store)
        except Exception as exc:  # noqa: BLE001 转录旁路绝不反噬执行
            logger.warning("sub_agent_transcript_record_failed", error=str(exc))

    async def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        if self._handler is None:
            return
        payload = {"source": self._source, "run_id": self.run_id, **data}
        try:
            result = self._handler(AgentEvent(type=event_type, data=payload))
            if isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 进度旁路绝不反噬执行
            logger.warning(
                "sub_agent_progress_emit_failed", event_type=str(event_type), error=str(exc)
            )

    async def spawned(
        self, *, total: int, specs: list[str], message: str, stage: int | None = None
    ) -> None:
        self._record(
            lambda store: store.record_spawned(
                self.run_id, self._source, specs, stage=stage, message=message
            )
        )
        await self.emit(
            "sub_agent_spawned",
            {
                "total": total,
                "submitted": total,
                "reused": 0,
                "specs": specs,
                "stage": stage,
                "message": message,
            },
        )

    async def agent_done(
        self,
        *,
        role: str,
        completed: int,
        total: int,
        message: str,
        stage: int | None = None,
        error: str = "",
        skipped: bool = False,
    ) -> None:
        event_type = "sub_agent_failed" if (error or skipped) else "sub_agent_completed"
        self._record(
            lambda store: store.record_done(
                self.run_id, self._source, role, stage=stage, error=error, skipped=skipped
            )
        )
        await self.emit(
            event_type,
            {
                "spec_id": role,
                "role": role,
                "stage": stage,
                "completed": completed,
                "total": total,
                "error": error,
                "skipped": skipped,
                "message": message,
            },
        )

    def child_observer(self, role: str, stage: int | None = None) -> AgentEventHandler:
        """挂到子 AgentLoop 上：全文进转录存储，preview 转发到父会话。"""

        async def _observe(event: AgentEvent) -> None:
            if event.type not in _CHILD_FORWARD_TYPES:
                return
            kind, full, is_error = _describe_child_event(event)
            preview = clip_preview(f"✗ {full}" if is_error else full)
            if not preview:
                return
            self._record(
                lambda store: store.record_entry(
                    self.run_id, self._source, role, kind, full, stage=stage, is_error=is_error
                )
            )
            await self.emit(
                "sub_agent_progress",
                {"role": role, "stage": stage, "kind": kind, "preview": preview},
            )

        return _observe


def _describe_child_event(event: AgentEvent) -> tuple[str, str, bool]:
    """返回 (kind, 全文, is_error)；全文不截断，由存储层控制单条上限。"""
    data = event.data
    if event.type == "tool_call":
        name = getattr(data, "name", "")
        if not name:
            return "tool_call", "", False
        arguments = getattr(data, "arguments", None) or {}
        return "tool_call", f"{name}({arguments})", False
    if event.type == "tool_result":
        is_error = bool(getattr(data, "is_error", False))
        return "tool_result", str(getattr(data, "output", "") or ""), is_error
    return "message", str(getattr(data, "content", "") or ""), False


__all__ = ["ProgressSource", "SubAgentProgressEmitter", "clip_preview", "new_run_id"]
