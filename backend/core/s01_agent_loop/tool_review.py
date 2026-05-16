from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from backend.adapters.base import LLMAdapter
from backend.common.types import LLMRequest, Message, ToolCall

ReviewDecision = Literal["auto_approve", "require_human", "auto_reject"]
RiskLevel = Literal["low", "medium", "high"]


class ReviewResult(BaseModel):
    decision: ReviewDecision = "require_human"
    reason: str = "审核结果无法确认，需人工确认。"
    risk_level: RiskLevel = "medium"


class ToolReviewContext(BaseModel):
    plan_goal: str = ""
    current_step: str = ""
    step_description: str = ""


async def review_tool_calls(
    adapter: LLMAdapter,
    model: str,
    calls: list[ToolCall],
    context: ToolReviewContext,
) -> list[tuple[ToolCall, ReviewResult]]:
    request = LLMRequest(
        model=model,
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=_review_payload(calls, context)),
        ],
        temperature=0,
        max_tokens=1200,
    )
    try:
        response = await adapter.complete(request)
        results = _parse_review_results(response.content, len(calls))
    except Exception:
        results = [ReviewResult() for _ in calls]
    return list(zip(calls, results, strict=False))


def _parse_review_results(content: str, expected_count: int) -> list[ReviewResult]:
    try:
        raw = json.loads(_json_content(content))
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ValueError("review output is not a list")
        results = [ReviewResult.model_validate(_normalize_item(item)) for item in items]
    except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
        results = []
    while len(results) < expected_count:
        results.append(ReviewResult())
    return results[:expected_count]


def _json_content(content: str) -> str:
    stripped = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start_positions = [index for index in (stripped.find("["), stripped.find("{")) if index >= 0]
    end = max(stripped.rfind("]"), stripped.rfind("}"))
    if start_positions and end >= min(start_positions):
        return stripped[min(start_positions) : end + 1]
    return stripped


def _normalize_item(item: object) -> object:
    if not isinstance(item, dict):
        return item
    data = dict(item)
    decision = _canonical(str(data.get("decision", "")))
    risk = _canonical(str(data.get("risk_level", "")))
    if decision in {"approve", "approved", "allow", "allowed"}:
        data["decision"] = "auto_approve"
    elif decision in {"reject", "rejected", "deny", "denied"}:
        data["decision"] = "auto_reject"
    elif decision in {"human", "manual", "require_approval", "requires_approval"}:
        data["decision"] = "require_human"
    if risk in {"none", "safe"}:
        data["risk_level"] = "low"
    elif risk in {"moderate", "unknown"}:
        data["risk_level"] = "medium"
    return data


def _canonical(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _review_payload(calls: list[ToolCall], context: ToolReviewContext) -> str:
    payload = {
        "plan_goal": context.plan_goal,
        "current_step": context.current_step,
        "step_description": context.step_description,
        "tool_calls": [
            {"id": call.id, "tool_name": call.name, "tool_arguments": call.arguments}
            for call in calls
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


_SYSTEM_PROMPT = (
    "你是安全审核员，不是任务执行者。判断工具调用是否与任务目标和当前步骤一致。"
    "偏保守：不确定就输出 require_human。关注生产环境、批量、删除、金钱、"
    "收件人或目标范围与步骤不一致等风险。只输出 JSON 数组，每项包含 "
    "decision、reason、risk_level。"
)


__all__ = ["ReviewResult", "ToolReviewContext", "review_tool_calls"]
