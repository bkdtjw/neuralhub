from __future__ import annotations

from .plan_execute_errors import PlanExecuteError
from .plan_models import PlanPhase

TERMINAL_PHASES = frozenset(
    {PlanPhase.COMPLETED, PlanPhase.PARTIAL_FAILED, PlanPhase.CANCELLED}
)

PLAN_TRANSITIONS: frozenset[tuple[PlanPhase, PlanPhase]] = frozenset(
    {
        (PlanPhase.IDLE, PlanPhase.RECON),
        (PlanPhase.RECON, PlanPhase.PLANNING),
        (PlanPhase.PLANNING, PlanPhase.RECON),
        (PlanPhase.PLANNING, PlanPhase.PLAN_READY),
        (PlanPhase.PLAN_READY, PlanPhase.AWAITING_APPROVAL),
        (PlanPhase.AWAITING_APPROVAL, PlanPhase.EXECUTING),
        (PlanPhase.EXECUTING, PlanPhase.COMPLETED),
        (PlanPhase.EXECUTING, PlanPhase.PARTIAL_FAILED),
        (PlanPhase.EXECUTING, PlanPhase.PAUSED),
        (PlanPhase.PAUSED, PlanPhase.EXECUTING),
        (PlanPhase.IDLE, PlanPhase.CANCELLED),
        (PlanPhase.RECON, PlanPhase.CANCELLED),
        (PlanPhase.PLANNING, PlanPhase.CANCELLED),
        (PlanPhase.PLAN_READY, PlanPhase.CANCELLED),
        (PlanPhase.AWAITING_APPROVAL, PlanPhase.CANCELLED),
        (PlanPhase.EXECUTING, PlanPhase.CANCELLED),
        (PlanPhase.PAUSED, PlanPhase.CANCELLED),
    }
)


def validate_transition(current: PlanPhase, target: PlanPhase) -> bool:
    return (current, target) in PLAN_TRANSITIONS


def transition(current: PlanPhase, target: PlanPhase) -> PlanPhase:
    if not validate_transition(current, target):
        raise PlanExecuteError(
            "PLAN_INVALID_TRANSITION",
            f"Invalid phase transition: {current.value} → {target.value}",
        )
    return target


def is_terminal(phase: PlanPhase) -> bool:
    return phase in TERMINAL_PHASES


__all__ = [
    "PLAN_TRANSITIONS",
    "TERMINAL_PHASES",
    "is_terminal",
    "transition",
    "validate_transition",
]
