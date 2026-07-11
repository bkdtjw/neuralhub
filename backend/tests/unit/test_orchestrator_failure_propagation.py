from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

import backend.core.s04_sub_agents.orchestrator as orchestrator_module
from backend.common.types import SimplePlan, SubAgentResult
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import Orchestrator
from backend.core.s04_sub_agents.runtime_models import IsolatedAgentRun, IsolatedAgentRuntime

from .sub_agent_test_support import ScenarioAdapter, build_orchestrator_config, build_task


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拉起容器。
    yield


class _RecordingRunner:
    """替换 run_isolated_agent：记录哪些角色被真正执行及各自看到的依赖输入。"""

    def __init__(self, outcomes: dict[str, tuple[str, bool]]) -> None:
        self._outcomes = outcomes
        self.invoked: list[str] = []
        self.dependency_seen: dict[str, dict[str, str]] = {}

    async def run_isolated_agent(
        self,
        run: IsolatedAgentRun,
        runtime: IsolatedAgentRuntime,
        on_event: object | None = None,
    ) -> SubAgentResult:
        role = run.task.role
        self.invoked.append(role)
        self.dependency_seen[role] = dict(run.dependency_outputs)
        output, is_error = self._outcomes[role]
        return SubAgentResult(role=role, stage_id=-1, output=output, is_error=is_error)


def _build_orchestrator() -> Orchestrator:
    return Orchestrator(
        adapter=ScenarioAdapter(lambda _message: "ok"),
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(),
    )


def _two_stage_plan() -> SimplePlan:
    return SimplePlan(
        tasks=[
            build_task("A", "审查代码"),
            build_task("B", "根据审查结果修复", permission="readwrite", depends_on=["A"]),
        ]
    )


@pytest.mark.asyncio
async def test_upstream_failure_short_circuits_downstream(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _RecordingRunner({"A": ("A 执行失败：数据库连接被拒绝", True)})
    monkeypatch.setattr(orchestrator_module, "run_isolated_agent", runner.run_isolated_agent)

    result = await _build_orchestrator().execute(_two_stage_plan())

    # B 未被真正执行——run_isolated_agent 从未因 B 被调用。
    assert runner.invoked == ["A"]
    assert "B" not in runner.dependency_seen
    # B 的产物是跳过说明，而非基于 A 错误文本的下游产物。
    assert "[B] [跳过(上游失败)]" in result.output
    assert "上游依赖 A 失败，已跳过执行。" in result.output
    # A 仍标记为失败，B 标记为错误（跳过也是 is_error），整体报错。
    assert "[A] [失败]" in result.output
    assert result.is_error is True
    # 报告在汇总行区分“失败”与“跳过”。
    assert "1 个子任务失败" in result.output
    assert "1 个子任务因上游失败被跳过" in result.output


@pytest.mark.asyncio
async def test_successful_upstream_feeds_downstream(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _RecordingRunner(
        {
            "A": ("发现 N+1 查询", False),
            "B": ("已根据审查结果修复", False),
        }
    )
    monkeypatch.setattr(orchestrator_module, "run_isolated_agent", runner.run_isolated_agent)

    result = await _build_orchestrator().execute(_two_stage_plan())

    # A 成功后 B 正常执行，并拿到 A 的成功 output 作为依赖。
    assert runner.invoked == ["A", "B"]
    assert runner.dependency_seen["B"] == {"A": "发现 N+1 查询"}
    assert result.is_error is False
    assert "[A] [完成]" in result.output
    assert "[B] [完成]" in result.output
    assert "已根据审查结果修复" in result.output
    assert "跳过" not in result.output
