from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanPhase(str, Enum):  # noqa: UP042
    """Persisted phase for Plan & Execute mode."""

    IDLE = "idle"
    RECON = "recon"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    CANCELLED = "cancelled"


class PlanStep(BaseModel):
    """One design-level step in an execution plan."""

    step_id: int
    title: str
    description: str
    tools_hint: list[str] = Field(default_factory=list)
    type: Literal["script_step", "agent_step"] = "agent_step"
    tool_name: str = ""
    tool_arguments: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """Persisted plan document written as plan markdown."""

    goal: str
    approach: list[str] = Field(default_factory=list)
    data_structures: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    version: int = 1


class TodoStep(BaseModel):
    """Runtime progress for one plan step."""

    id: int
    title: str
    status: str = "pending"
    duration_s: float = 0.0
    key_findings: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    output_summary: str = ""
    checkpoint_session_id: str = ""


class TodoState(BaseModel):
    """Complete runtime progress tracked as todo json."""

    plan_name: str
    session_id: str
    status: str = "pending"
    steps: list[TodoStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class PlanState(BaseModel):
    """Persisted runtime state for one Plan & Execute run."""

    plan_name: str
    session_id: str
    owner_id: str = "unknown"
    phase: PlanPhase = PlanPhase.IDLE
    plan: ExecutionPlan | None = None
    todo: TodoState | None = None
    current_step_id: int = 0
    error_message: str = ""
    interrupted_at: datetime | None = None
    resume_point: str = ""
    todo_update_count: int = 0
    recon_report: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


__all__ = [
    "ExecutionPlan",
    "PlanPhase",
    "PlanState",
    "PlanStep",
    "TodoState",
    "TodoStep",
]
