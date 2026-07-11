from __future__ import annotations

from typing import Any

from backend.common.types import AgentEvent

_SUB_AGENT_WS_TYPES = {
    "sub_agent_spawned",
    "sub_agent_completed",
    "sub_agent_failed",
    "sub_agent_progress",
}


def sub_agent_event_to_ws(event: AgentEvent) -> dict[str, Any] | None:
    """把子 agent 进度事件序列化为 WS 消息；非子 agent 事件返回 None。

    source/run_id/stage/role 是面板可视化的分组键：
    source=orchestrate|dispatch|spawn，run_id 关联一次多 agent 调用。
    """
    if event.type not in _SUB_AGENT_WS_TYPES or not isinstance(event.data, dict):
        return None
    data: dict[str, Any] = event.data
    common = {
        "type": event.type,
        "source": data.get("source"),
        "run_id": data.get("run_id"),
        "stage": data.get("stage"),
    }
    if event.type == "sub_agent_spawned":
        return {
            **common,
            "total": data.get("total"),
            "submitted": data.get("submitted"),
            "reused": data.get("reused"),
            "specs": data.get("specs"),
            "message": data.get("message"),
        }
    if event.type == "sub_agent_progress":
        return {
            **common,
            "role": data.get("role"),
            "kind": data.get("kind"),
            "preview": data.get("preview"),
        }
    return {
        **common,
        "task_id": data.get("task_id"),
        "spec_id": data.get("spec_id"),
        "role": data.get("role") or data.get("spec_id"),
        "completed": data.get("completed"),
        "total": data.get("total"),
        "error": data.get("error"),
        "skipped": data.get("skipped"),
        "message": data.get("message"),
    }


__all__ = ["sub_agent_event_to_ws"]
