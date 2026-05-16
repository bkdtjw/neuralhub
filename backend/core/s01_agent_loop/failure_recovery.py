from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field

from backend.common.types import ToolCall, ToolResult

RECOVERY_CONTEXT_HEADER = "[失败恢复提示]"
REPEATED_FAILURE_HEADER = "[重复失败拦截]"


class ToolFailureState(BaseModel):
    signature: str
    call_summary: str
    count: int = 0
    last_fingerprint: str = ""
    recent_errors: list[str] = Field(default_factory=list)


class ToolFailureRecoveryTracker:
    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self._consecutive_failures = 0
        self._states: dict[str, ToolFailureState] = {}
        self._recent_fingerprints: list[str] = []

    def split_repeated(self, calls: list[ToolCall]) -> tuple[list[ToolCall], list[ToolResult]]:
        if self._threshold <= 0:
            return calls, []
        allowed: list[ToolCall] = []
        skipped: list[ToolResult] = []
        for call in calls:
            state = self._states.get(_signature(call))
            if state is None or state.count < self._threshold:
                allowed.append(call)
                continue
            skipped.append(
                ToolResult(
                    tool_call_id=call.id,
                    output=_build_repeated_failure_output(state),
                    is_error=True,
                )
            )
        return allowed, skipped

    def annotate(self, results: list[ToolResult], call_map: dict[str, ToolCall]) -> list[ToolResult]:
        if self._threshold <= 0:
            return results
        annotated: list[ToolResult] = []
        for result in results:
            call = call_map.get(result.tool_call_id)
            if call is None:
                annotated.append(result)
                continue
            if not result.is_error:
                self._record_success(call)
                annotated.append(result)
                continue
            if result.output.startswith(REPEATED_FAILURE_HEADER):
                annotated.append(result)
                continue
            state = self._record_failure(call, result)
            if self._should_add_context(state):
                annotated.append(_append_recovery_context(result, state, self._recent_fingerprints))
            else:
                annotated.append(result)
        return annotated

    def _record_success(self, call: ToolCall) -> None:
        self._consecutive_failures = 0
        self._states.pop(_signature(call), None)

    def record_success(self, call: ToolCall) -> None:
        self._record_success(call)

    def _record_failure(self, call: ToolCall, result: ToolResult) -> ToolFailureState:
        self._consecutive_failures += 1
        signature = _signature(call)
        state = self._states.get(signature)
        if state is None:
            state = ToolFailureState(signature=signature, call_summary=_call_summary(call))
            self._states[signature] = state
        fingerprint = _fingerprint(call, result)
        state.count += 1
        state.last_fingerprint = fingerprint
        state.recent_errors = [*state.recent_errors[-2:], _error_summary(result.output)]
        self._recent_fingerprints = [*self._recent_fingerprints[-4:], fingerprint]
        return state

    def _should_add_context(self, state: ToolFailureState) -> bool:
        return state.count >= self._threshold or self._consecutive_failures >= self._threshold


def _append_recovery_context(
    result: ToolResult,
    state: ToolFailureState,
    recent_fingerprints: list[str],
) -> ToolResult:
    context = "\n".join(
        [
            "",
            RECOVERY_CONTEXT_HEADER,
            f"相同调用失败次数: {state.count}",
            f"失败指纹: {state.last_fingerprint}",
            f"调用摘要: {state.call_summary}",
            "不要再次用相同工具和相同参数重试。",
            "请先分析失败原因，然后换策略：读取上下文、缩小范围、换工具、改参数，或询问用户。",
            "最近失败指纹: " + ", ".join(recent_fingerprints[-3:]),
        ]
    )
    return result.model_copy(update={"output": f"{result.output.rstrip()}{context}"})


def _build_repeated_failure_output(state: ToolFailureState) -> str:
    return "\n".join(
        [
            REPEATED_FAILURE_HEADER,
            "该工具调用与最近失败指纹相同，已跳过真实执行。",
            f"失败指纹: {state.last_fingerprint}",
            f"调用摘要: {state.call_summary}",
            "请换工具、换参数，或先解释失败原因后再继续。",
        ]
    )


def _signature(call: ToolCall) -> str:
    payload = f"{call.name}:{_normalized_args(call.arguments)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{call.name}:{digest}"


def _fingerprint(call: ToolCall, result: ToolResult) -> str:
    return f"{_signature(call)}:{_error_kind(result.output)}"


def _normalized_args(arguments: dict[str, object]) -> str:
    return _shorten(json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str), 240)


def _call_summary(call: ToolCall) -> str:
    detail = call.arguments.get("command") or call.arguments.get("path") or call.arguments.get("url")
    if not isinstance(detail, str) or not detail.strip():
        detail = _normalized_args(call.arguments)
    return _shorten(f"{call.name}({detail})", 260)


def _error_kind(output: str) -> str:
    patterns = [
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
        r"\b(exit code \d+)\b",
        r"\b(status(?: code)? \d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.I)
        if match:
            return match.group(1).replace(" ", "_")
    lowered = output.lower()
    for marker in ("permission denied", "not found", "no such file", "timeout", "connection"):
        if marker in lowered:
            return marker.replace(" ", "_")
    return _shorten(_error_summary(output), 48) or "unknown_error"


def _error_summary(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return _shorten(lines[0] if lines else "empty error", 160)


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."


__all__ = [
    "RECOVERY_CONTEXT_HEADER",
    "REPEATED_FAILURE_HEADER",
    "ToolFailureRecoveryTracker",
]
