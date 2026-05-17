from __future__ import annotations

import asyncio
from typing import Any

from backend.common.types import ToolCall, ToolResult

from .tool_review import review_tool_calls


class AgentLoopApprovalMixin:
    _aborted: bool
    _adapter: Any
    _config: Any
    _owner_id: str
    _tool_approval_decisions: dict[str, bool]
    _tool_approval_events: dict[str, asyncio.Event]
    _tool_approval_reasons: dict[str, str]
    _tool_approval_timeout_seconds: float
    _tool_review_context: Any
    _user_config_store: Any

    def approve_tool_call(self, tool_call_id: str) -> bool:
        return self._resolve_tool_call(tool_call_id, approved=True)

    def reject_tool_call(self, tool_call_id: str) -> bool:
        return self._resolve_tool_call(tool_call_id, approved=False)

    async def wait_tool_approvals(
        self,
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolCall], list[ToolResult]]:
        approved: list[ToolCall] = []
        rejected: list[ToolResult] = []
        for call in tool_calls:
            self._tool_approval_events[call.id] = asyncio.Event()
        try:
            self._emit_approval_required(tool_calls)
            for call in tool_calls:
                await self._wait_one_approval(call, approved, rejected)
        finally:
            for call in tool_calls:
                self._tool_approval_events.pop(call.id, None)
                self._tool_approval_decisions.pop(call.id, None)
                self._tool_approval_reasons.pop(call.id, None)
        return approved, rejected

    async def review_tool_approvals(
        self,
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolCall], list[ToolResult], list[ToolCall]]:
        if not self._user_config_store.get(self._owner_id).auto_approve_tools:
            return [], [], tool_calls
        reviewed = await review_tool_calls(
            self._adapter,
            self._config.model,
            tool_calls,
            self._tool_review_context,
        )
        approved: list[ToolCall] = []
        rejected: list[ToolResult] = []
        human: list[ToolCall] = []
        for call, review in reviewed:
            if review.decision == "auto_approve":
                approved.append(call)
            elif review.decision == "auto_reject":
                rejected.append(_approval_result(call, f"自动拒绝：{review.reason}"))
            else:
                if review.reason:
                    self._tool_approval_reasons[call.id] = review.reason
                human.append(call)
        return approved, rejected, human

    def _resolve_tool_call(self, tool_call_id: str, approved: bool) -> bool:
        event = self._tool_approval_events.get(tool_call_id)
        if event is None:
            return False
        self._tool_approval_decisions[tool_call_id] = approved
        event.set()
        return True

    def _emit_approval_required(self, tool_calls: list[ToolCall]) -> None:
        self._emit(
            "tool_approval_required",
            {
                "tool_calls": [self._approval_payload(call) for call in tool_calls],
                "timeout_seconds": self._tool_approval_timeout_seconds,
            },
        )

    def _approval_payload(self, call: ToolCall) -> dict[str, Any]:
        payload = call.model_dump(mode="json")
        reason = self._tool_approval_reasons.get(call.id, "")
        if reason:
            payload["approval_reason"] = reason
        return payload

    async def _wait_one_approval(
        self,
        call: ToolCall,
        approved: list[ToolCall],
        rejected: list[ToolResult],
    ) -> None:
        if self._aborted:
            rejected.append(_approval_result(call, "工具调用已取消。"))
            return
        try:
            await asyncio.wait_for(
                self._tool_approval_events[call.id].wait(),
                timeout=self._tool_approval_timeout_seconds,
            )
        except TimeoutError:
            self._tool_approval_decisions[call.id] = False
        if self._tool_approval_decisions.get(call.id) is True:
            approved.append(call)
        else:
            rejected.append(_approval_result(call, "工具调用未获得人工审批。"))


def _approval_result(tool_call: ToolCall, reason: str) -> ToolResult:
    return ToolResult(tool_call_id=tool_call.id, output=reason, is_error=True)


__all__ = ["AgentLoopApprovalMixin"]
