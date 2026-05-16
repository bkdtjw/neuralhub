from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.core.s01_agent_loop import PlanCheckpointStore, PlanExecuteRunner, PlanRenderer


class FeishuPlanRunnerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider_manager: ProviderManager
    chat_id: str
    renderer: PlanRenderer
    agent_runtime: Any | None = None
    spec_id: str = ""
    task_queue: Any | None = None
    owner_id: str = ""


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
        owner_id=payload.owner_id or payload.chat_id,
    )
    if not isinstance(runner, PlanExecuteRunner):
        raise AgentError("FEISHU_PLAN_RUNNER_TYPE_ERROR", "plan mode did not create runner")
    return runner


async def create_feishu_resume_runner(
    payload: FeishuPlanRunnerInput,
    checkpoint_store: PlanCheckpointStore,
) -> PlanExecuteRunner | None:
    base = await create_feishu_plan_runner(payload)
    owner_id = payload.owner_id or payload.chat_id
    resumed = PlanExecuteRunner.resume_from_checkpoint(
        checkpoint_store,
        f"feishu-{payload.chat_id}",
        base._adapter,
        base._tool_registry,
        base._plan_store,
        base._todo_store,
        payload.renderer,
        bridge=base.bridge,
        agent_spec=base.agent_spec,
        owner_id=owner_id,
    )
    if resumed is None:
        return None
    base._state = resumed._state
    base._checkpoint_path = resumed._checkpoint_path
    base._plan_path = resumed._plan_path
    base._todo_path = resumed._todo_path
    return base


__all__ = [
    "FeishuPlanRunnerInput",
    "create_feishu_plan_runner",
    "create_feishu_resume_runner",
]
