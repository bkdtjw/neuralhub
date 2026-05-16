from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict

from backend.common import sanitize_message_history
from backend.common.errors import AgentError
from backend.common.types import AgentEvent, Message, Session, ToolCall, ToolResult
from backend.core.s01_agent_loop import AgentLoop
from backend.storage import SessionStore

from .websocket_plan_events import plan_event_to_ws_message


class LoopSettings(BaseModel):
    model: str = ""
    provider_id: str | None = None
    workspace: str | None = None
    permission_mode: str = "auto"
    spec_id: str = ""
    mode: str = "direct"


class RunLoopInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    loop: AgentLoop
    message: str
    send_message: Callable[[dict[str, Any]], Awaitable[None]]
    session_id: str
    store: SessionStore | None = None


def get_store(websocket: WebSocket) -> SessionStore | None:
    return getattr(websocket.app.state, "session_store", None)


def parse_loop_settings(data: dict[str, Any]) -> LoopSettings:
    spec_id = str(data.get("spec_id", "")).strip()
    model = str(data.get("model", "")).strip()
    if not model and not spec_id:
        raise AgentError("MODEL_REQUIRED", "model is required")
    return LoopSettings(
        model=model,
        provider_id=str(data.get("provider_id", "")).strip() or None,
        workspace=str(data.get("workspace", "")).strip() or None,
        permission_mode=str(data.get("permission_mode", "auto")).strip() or "auto",
        spec_id=spec_id,
        mode=str(data.get("mode", "direct")).strip() or "direct",
    )


async def resolve_loop_settings(settings: LoopSettings, provider_manager: Any) -> LoopSettings:
    try:
        if settings.spec_id:
            return settings
        if settings.provider_id is not None:
            return settings
        default_provider = await provider_manager.get_default()
        provider_id = default_provider.id if default_provider is not None else None
        return settings.model_copy(update={"provider_id": provider_id})
    except Exception as exc:  # noqa: BLE001
        raise AgentError("WS_RESOLVE_SETTINGS_ERROR", str(exc)) from exc


def restore_messages(
    messages: list[Message],
    system_prompt: str,
    clear_provider_metadata: bool = False,
) -> list[Message]:
    restored = [Message(role="system", content=system_prompt)]
    for message in messages:
        if message.role == "system":
            continue
        cloned = message.model_copy(deep=True)
        if clear_provider_metadata:
            cloned.provider_metadata = {}
        restored.append(cloned)
    return sanitize_message_history(restored)


def serialize_message_for_client(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tool_calls": [call.model_dump(mode="json") for call in message.tool_calls or []],
        "tool_results": [result.model_dump(mode="json") for result in message.tool_results or []],
        "timestamp": message.timestamp.isoformat(),
    }


def serialize_session_for_client(session: Session, messages: list[Message]) -> dict[str, Any]:
    payload = session.model_dump(mode="json", exclude={"messages"})
    payload["messages"] = [serialize_message_for_client(message) for message in messages]
    return payload


def tool_result_payload(message_type: str, data: ToolResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": message_type,
        "tool_call_id": data.tool_call_id,
        "output": data.output,
        "is_error": data.is_error,
    }
    if data.diffs:
        payload["diffs"] = [diff.model_dump(mode="json") for diff in data.diffs]
    return payload


def event_to_ws_message(event: AgentEvent) -> dict[str, Any]:
    data = event.data
    if event.type == "status_change":
        return {"type": "status", "status": data}
    if event.type == "message" and isinstance(data, Message):
        return {
            "type": "message",
            "content": data.content,
            "tool_calls": [call.model_dump() for call in data.tool_calls or []],
        }
    if event.type == "tool_call" and isinstance(data, ToolCall):
        return {"type": "tool_call", "id": data.id, "name": data.name, "arguments": data.arguments}
    if event.type == "tool_result" and isinstance(data, ToolResult):
        return tool_result_payload("tool_result", data)
    if event.type == "tool_approval_required" and isinstance(data, dict):
        return {"type": "tool_approval_required", **data}
    if event.type == "security_reject" and isinstance(data, ToolResult):
        return tool_result_payload("security_reject", data)
    if event.type == "sub_agent_spawned" and isinstance(data, dict):
        return {
            "type": "sub_agent_spawned",
            "total": data.get("total"),
            "specs": data.get("specs"),
            "message": data.get("message"),
        }
    if event.type in {"sub_agent_completed", "sub_agent_failed"} and isinstance(data, dict):
        return {
            "type": event.type,
            "task_id": data.get("task_id"),
            "spec_id": data.get("spec_id"),
            "completed": data.get("completed"),
            "total": data.get("total"),
            "error": data.get("error"),
            "message": data.get("message"),
        }
    plan_message = plan_event_to_ws_message(event)
    if plan_message is not None:
        return plan_message
    return {"type": "error", "message": str(getattr(data, "message", data))}


async def run_loop(payload: RunLoopInput) -> None:
    try:
        result = await payload.loop.run(payload.message)
        try:
            await payload.send_message(
                {
                    "type": "done",
                    "message": serialize_message_for_client(result) if result else None,
                }
            )
        except Exception:
            return
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await payload.send_message({"type": "error", "message": str(exc)})
        except Exception:
            return
    finally:
        history = payload.loop.message_history
        has_checkpoint = history.has_checkpoint_fn
        checkpoint_failed = history.checkpoint_failed
        if payload.store is not None and (not has_checkpoint or checkpoint_failed):
            try:
                await payload.store.save_messages(payload.session_id, payload.loop.messages)
            except Exception:
                pass


__all__ = [
    "LoopSettings",
    "RunLoopInput",
    "event_to_ws_message",
    "get_store",
    "parse_loop_settings",
    "resolve_loop_settings",
    "restore_messages",
    "run_loop",
    "serialize_message_for_client",
    "serialize_session_for_client",
    "tool_result_payload",
]
