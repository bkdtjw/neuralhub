from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PlanStatus(str, Enum):  # noqa: UP042
    """Runner state machine for Plan & Execute mode."""

    IDLE = "idle"
    RECON = "recon"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
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


class TodoState(BaseModel):
    """Complete runtime progress tracked as todo json."""

    plan_name: str
    session_id: str
    status: str = "pending"
    steps: list[TodoStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


__all__ = [
    "ExecutionPlan",
    "PlanStatus",
    "PlanStep",
    "TodoState",
    "TodoStep",
]
