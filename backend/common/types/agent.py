from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentStatus = Literal[
    "idle",
    "thinking",
    "compacting",
    "tool_calling",
    "waiting_approval",
    "done",
    "error",
]

AgentEventType = Literal[
    "status_change",
    "message",
    "tool_call",
    "tool_result",
    "tool_approval_required",
    "security_reject",
    "sub_agent_spawned",
    "sub_agent_completed",
    "sub_agent_failed",
    "error",
    "plan_recon_start",
    "plan_recon_done",
    "plan_created",
    "plan_approved",
    "plan_step_start",
    "plan_step_done",
    "plan_step_failed",
    "plan_amendment",
    "plan_steps_updated",
    "plan_completed",
    "plan_partial_failed",
    "plan_cancelled",
]


class AgentConfig(BaseModel):
    model: str
    provider: str = "anthropic"
    system_prompt: str = ""
    session_id: str = ""
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = 20
    max_consecutive_tool_failures: int = 3
    timeout_seconds: float = 300.0


class AgentEvent(BaseModel):
    type: AgentEventType
    data: Any = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


type AgentEventHandler = Callable[[AgentEvent], Awaitable[None] | None]


__all__ = [
    "AgentStatus",
    "AgentEventType",
    "AgentConfig",
    "AgentEvent",
    "AgentEventHandler",
]
