from __future__ import annotations

import hmac
import json
import secrets
import time
from hashlib import sha256

from pydantic import BaseModel, Field

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import SecurityPolicy, SignedToolCall, ToolCall, ToolResult

from .registry import ToolRegistry

logger = get_logger(component="security_gate")


class SecurityGateError(AgentError):
    """安全关卡校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message)


class AuthorizeResult(BaseModel):
    """安全关卡授权结果。"""

    signed_calls: list[SignedToolCall] = Field(default_factory=list)
    rejected_results: list[ToolResult] = Field(default_factory=list)
    pending_approval: list[ToolCall] = Field(default_factory=list)


class SecurityGate:
    def __init__(self, policy: SecurityPolicy, registry: ToolRegistry) -> None:
        self._policy = policy
        self._registry = registry
        self._session_key = secrets.token_bytes(32)
        self._sequence = 0
        self._last_verified_sequence = 0

    @property
    def session_key(self) -> bytes:
        return self._session_key

    def authorize(self, tool_calls: list[ToolCall]) -> AuthorizeResult:
        try:
            result = AuthorizeResult()
            for tool_call in tool_calls:
                reason = self._reject_reason(tool_call, len(result.signed_calls))
                if reason.startswith("requires_approval:"):
                    result.pending_approval.append(tool_call)
                    continue
                if reason:
                    logger.warning("tool_rejected", tool=tool_call.name, tool_call_id=tool_call.id, reason=reason)
                    result.rejected_results.append(self._rejected_result(tool_call, reason))
                    continue
                self._sequence += 1
                timestamp = time.time()
                result.signed_calls.append(
                    SignedToolCall(
                        tool_call=tool_call,
                        sequence=self._sequence,
                        timestamp=timestamp,
                        signature=self._sign(tool_call, self._sequence, timestamp),
                    )
                )
            return result
        except Exception as exc:
            raise SecurityGateError("SECURITY_AUTHORIZE_FAILED", str(exc)) from exc

    def verify(self, signed_call: SignedToolCall) -> bool:
        try:
            expected = self._sign(
                signed_call.tool_call,
                signed_call.sequence,
                signed_call.timestamp,
            )
            if not hmac.compare_digest(expected, signed_call.signature):
                return False
            if signed_call.sequence <= self._last_verified_sequence:
                return False
            self._last_verified_sequence = signed_call.sequence
            return True
        except Exception:
            return False

    def force_sign(self, tool_calls: list[ToolCall]) -> list[SignedToolCall]:
        try:
            signed: list[SignedToolCall] = []
            for tool_call in tool_calls:
                self._sequence += 1
                timestamp = time.time()
                signed.append(
                    SignedToolCall(
                        tool_call=tool_call,
                        sequence=self._sequence,
                        timestamp=timestamp,
                        signature=self._sign(tool_call, self._sequence, timestamp),
                    )
                )
            return signed
        except Exception as exc:
            raise SecurityGateError("SECURITY_FORCE_SIGN_FAILED", str(exc)) from exc

    def reset(self) -> None:
        self._sequence = 0
        self._last_verified_sequence = 0

    def _reject_reason(self, tool_call: ToolCall, signed_count: int) -> str:
        if not self._registry.has(tool_call.name):
            return f"unknown tool: {tool_call.name}"
        if self._policy.allowed_tools and tool_call.name not in self._policy.allowed_tools:
            return f"tool not allowed: {tool_call.name}"
        if signed_count >= self._policy.max_calls_per_turn:
            return f"max calls per turn exceeded: {self._policy.max_calls_per_turn}"
        tool = self._registry.get(tool_call.name)
        if tool is not None and tool[0].permission.requires_approval:
            return f"requires_approval:{tool_call.name}"
        return ""

    def _sign(self, tool_call: ToolCall, sequence: int, timestamp: float) -> str:
        payload = self._payload(tool_call, sequence, timestamp)
        return hmac.new(self._session_key, payload, sha256).hexdigest()

    @staticmethod
    def _payload(tool_call: ToolCall, sequence: int, timestamp: float) -> bytes:
        arguments = json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)
        return f"{tool_call.name}|{arguments}|{sequence}|{timestamp}".encode()

    @staticmethod
    def _rejected_result(tool_call: ToolCall, reason: str) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            output=f"SecurityGate rejected: {reason}",
            is_error=True,
        )


__all__ = ["AuthorizeResult", "SecurityGate", "SecurityGateError"]
