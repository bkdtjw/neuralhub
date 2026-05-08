from __future__ import annotations

from typing import Any

from backend.common.types import AgentEvent


def plan_event_to_ws_message(event: AgentEvent) -> dict[str, Any] | None:
    data = event.data
    if event.type == "plan_recon_start" and isinstance(data, dict):
        return {"type": "plan_recon_start", "goal": data.get("goal", "")}
    if event.type == "plan_recon_done" and isinstance(data, dict):
        return {"type": "plan_recon_done", "report_preview": data.get("report_preview", "")}
    if event.type == "plan_created" and isinstance(data, dict):
        return {
            "type": "plan_created",
            "plan_name": data.get("plan_name", ""),
            "goal": data.get("goal", ""),
            "steps": data.get("steps", []),
        }
    if event.type == "plan_approved":
        return {"type": "plan_approved", "plan_name": data}
    if event.type == "plan_step_start" and isinstance(data, dict):
        return {
            "type": "plan_step_update",
            "step_id": data.get("step_id"),
            "status": "running",
            "title": data.get("title", ""),
            "total_steps": data.get("total_steps"),
        }
    if event.type == "plan_step_done" and isinstance(data, dict):
        return {
            "type": "plan_step_update",
            "step_id": data.get("step_id"),
            "status": "done",
            "title": data.get("title", ""),
            "duration_s": data.get("duration_s"),
            "output_summary": data.get("output_summary", ""),
        }
    if event.type == "plan_step_failed" and isinstance(data, dict):
        return {
            "type": "plan_step_update",
            "step_id": data.get("step_id"),
            "status": "failed",
            "title": data.get("title", ""),
            "error": data.get("error", ""),
        }
    if event.type == "plan_amendment" and isinstance(data, dict):
        return {
            "type": "plan_amendment",
            "plan_name": data.get("plan_name", ""),
            "version": data.get("version"),
            "reason": data.get("reason", ""),
        }
    if event.type == "plan_steps_updated" and isinstance(data, dict):
        return {
            "type": "plan_steps_updated",
            "plan_name": data.get("plan_name", ""),
            "steps": data.get("steps", []),
            "todo_steps": data.get("todo_steps", []),
        }
    if event.type == "plan_partial_failed" and isinstance(data, dict):
        return {
            "type": "plan_partial_failed",
            "plan_name": data.get("plan_name", ""),
            "done": data.get("done"),
            "failed": data.get("failed"),
        }
    if event.type in {"plan_completed", "plan_cancelled"} and isinstance(data, dict):
        return {"type": event.type, "plan_name": data.get("plan_name", "")}
    return None


__all__ = ["plan_event_to_ws_message"]
