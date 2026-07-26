"""子 agent 运行转录查询：面板点击某个子 agent 时拉取完整活动记录。

数据来自 s04_sub_agents 的进程内转录存储（WS preview 事件的全文版），
只保留最近若干次运行；后端重启即清空，前端需对 404 做实时预览兜底。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.middleware.auth import verify_token
from backend.core.s04_sub_agents import (
    AgentTranscript,
    RunSummary,
    RunTranscript,
    get_sub_agent_transcript_store,
)

router = APIRouter(
    prefix="/api/sub-agent-runs",
    tags=["sub-agents"],
    dependencies=[Depends(verify_token)],
)


class RunListResponse(BaseModel):
    runs: list[RunSummary] = Field(default_factory=list)


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


@router.get("", response_model=RunListResponse)
async def list_sub_agent_runs() -> RunListResponse:
    return RunListResponse(runs=get_sub_agent_transcript_store().list_runs())


@router.get("/{run_id}", response_model=RunTranscript)
async def get_sub_agent_run(run_id: str) -> RunTranscript:
    run = get_sub_agent_transcript_store().get_run(run_id)
    if run is None:
        raise _not_found("SUB_AGENT_RUN_NOT_FOUND", f"Unknown sub-agent run: {run_id}")
    return run


@router.get("/{run_id}/agents/{role}", response_model=AgentTranscript)
async def get_sub_agent_transcript(run_id: str, role: str) -> AgentTranscript:
    agent = get_sub_agent_transcript_store().get_agent(run_id, role)
    if agent is None:
        raise _not_found("SUB_AGENT_NOT_FOUND", f"Unknown sub-agent: {run_id}/{role}")
    return agent


__all__ = ["router"]
