from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

import backend.core.s04_sub_agents.orchestrator as orchestrator_module
from backend.common.types import SimplePlan, SubAgentResult
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import Orchestrator, OrchestratorConfig
from backend.core.s04_sub_agents.runtime_models import IsolatedAgentRun, IsolatedAgentRuntime

from .sub_agent_test_support import ScenarioAdapter, build_task


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拉起容器。
    yield


class _ConcurrencyProbe:
    """替换 run_isolated_agent，记录同时在跑的子 Agent 数量峰值。"""

    def __init__(self, hold: float = 0.02) -> None:
        self._hold = hold
        self._active = 0
        self.peak = 0
        self.completed: list[str] = []

    async def run_isolated_agent(
        self,
        run: IsolatedAgentRun,
        runtime: IsolatedAgentRuntime,
    ) -> SubAgentResult:
        self._active += 1
        self.peak = max(self.peak, self._active)
        try:
            await asyncio.sleep(self._hold)
        finally:
            self._active -= 1
        role = run.task.role
        self.completed.append(role)
        return SubAgentResult(role=role, stage_id=-1, output=f"done:{role}")


def _build_orchestrator(max_parallel_agents: int) -> Orchestrator:
    return Orchestrator(
        adapter=ScenarioAdapter(lambda _message: "ok"),
        parent_registry=ToolRegistry(),
        config=OrchestratorConfig(
            workspace="workspace",
            default_model="test-model",
            max_parallel_agents=max_parallel_agents,
        ),
    )


@pytest.mark.asyncio
async def test_run_stage_caps_parallel_sub_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _ConcurrencyProbe()
    monkeypatch.setattr(orchestrator_module, "run_isolated_agent", probe.run_isolated_agent)
    orchestrator = _build_orchestrator(max_parallel_agents=2)
    plan = SimplePlan(tasks=[build_task(f"role_{index}", f"任务 {index}") for index in range(5)])

    result = await orchestrator.execute(plan)

    assert result.is_error is False
    assert probe.peak == 2  # 5 个无依赖任务被闸门限制为最多 2 个同时在跑
    assert len(probe.completed) == 5
    assert sorted(probe.completed) == [f"role_{index}" for index in range(5)]
    for index in range(5):
        assert f"done:role_{index}" in result.output


@pytest.mark.asyncio
async def test_run_stage_parallelism_follows_config(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _ConcurrencyProbe()
    monkeypatch.setattr(orchestrator_module, "run_isolated_agent", probe.run_isolated_agent)
    orchestrator = _build_orchestrator(max_parallel_agents=5)
    plan = SimplePlan(tasks=[build_task(f"role_{index}", f"任务 {index}") for index in range(5)])

    await orchestrator.execute(plan)

    # 上限放宽到 5 时，同一阶段 5 个任务可全部并发——证明闸门跟随配置而非写死为 2。
    assert probe.peak == 5
    assert len(probe.completed) == 5


@pytest.mark.asyncio
async def test_default_max_parallel_agents_is_five() -> None:
    config = OrchestratorConfig(workspace="workspace", default_model="test-model")

    assert config.max_parallel_agents == 5
