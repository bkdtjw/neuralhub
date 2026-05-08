from __future__ import annotations

from backend.common.errors import AgentError


class PlanExecuteError(AgentError):
    pass


__all__ = ["PlanExecuteError"]
