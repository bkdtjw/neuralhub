from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.core.s01_agent_loop import PlanExecuteRunner, PlanRenderer


class FeishuPlanRunnerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider_manager: ProviderManager
    chat_id: str
    renderer: PlanRenderer
    agent_runtime: Any | None = None
    spec_id: str = ""
    task_queue: Any | None = None


async def create_feishu_plan_runner(payload: FeishuPlanRunnerInput) -> PlanExecuteRunner:
    _ = payload.provider_manager
    if payload.agent_runtime is None:
        raise AgentError("FEISHU_PLAN_RUNTIME_MISSING", "agent runtime is not available")
    runner = await payload.agent_runtime.create_runner(
        spec_id=payload.spec_id,
        mode="plan_execute",
        workspace=os.getcwd(),
        session_id=f"feishu-{payload.chat_id}",
        renderer=payload.renderer,
        task_queue=payload.task_queue,
    )
    if not isinstance(runner, PlanExecuteRunner):
        raise AgentError("FEISHU_PLAN_RUNNER_TYPE_ERROR", "plan mode did not create runner")
    return runner


__all__ = ["FeishuPlanRunnerInput", "create_feishu_plan_runner"]
