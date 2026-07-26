from __future__ import annotations

import asyncio

import pytest

from backend.common.types import SimplePlan
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import OrchestrationError, Orchestrator

from .sub_agent_test_support import ScenarioAdapter, build_orchestrator_config, build_task


@pytest.mark.asyncio
async def test_orchestrator_single_stage_report_format() -> None:
    orchestrator = Orchestrator(
        adapter=ScenarioAdapter(lambda _message: "发现一个问题"),
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(),
    )
    plan = SimplePlan(tasks=[build_task("reviewer", "审查代码")])

    result = await orchestrator.execute(plan)

    assert result.is_error is False
    assert "多 Agent 协作完成" in result.output
    assert "--- 阶段 0: reviewer ---" in result.output
    assert "[reviewer] [完成]" in result.output


@pytest.mark.asyncio
async def test_orchestrator_two_stage_pipeline_injects_dependency_output() -> None:
    adapter = ScenarioAdapter(
        lambda message: "发现 N+1 查询" if "审查代码" in message else "已根据审查结果修复",
    )
    plan = SimplePlan(
        tasks=[
            build_task("reviewer", "审查代码"),
            build_task("fixer", "修复问题", permission="readwrite", depends_on=["reviewer"]),
        ]
    )

    result = await Orchestrator(
        adapter=adapter,
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(),
    ).execute(plan)

    assert "发现 N+1 查询" in result.output
    assert "已根据审查结果修复" in result.output
    assert "[来自 reviewer 的结果]" in adapter.requests[1].messages[-1].content
    assert "发现 N+1 查询" in adapter.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_orchestrator_runs_same_stage_in_parallel() -> None:
    adapter = ScenarioAdapter(lambda message: f"完成:{message}", delay_fn=lambda _message: 0.03)
    plan = SimplePlan(tasks=[build_task("a", "检查 A"), build_task("b", "检查 B")])

    await Orchestrator(
        adapter=adapter,
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(),
    ).execute(plan)

    assert adapter.max_concurrency >= 2


def test_orchestrator_rejects_invalid_plan() -> None:
    orchestrator = Orchestrator(
        adapter=ScenarioAdapter(lambda _message: "ok"),
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(),
    )
    with pytest.raises(OrchestrationError):
        asyncio.run(orchestrator.execute(SimplePlan(tasks=[build_task("fixer", "执行", depends_on=["missing"])])))
    with pytest.raises(OrchestrationError):
        asyncio.run(orchestrator.execute(SimplePlan(tasks=[build_task("reviewer", "执行", depends_on=["reviewer"])])))
    with pytest.raises(OrchestrationError):
        asyncio.run(
            orchestrator.execute(
                SimplePlan(tasks=[build_task("a", "执行"), build_task("a", "重复执行")])
            )
        )


@pytest.mark.asyncio
async def test_orchestrator_timeout_marks_result_as_error() -> None:
    # 时序预算给足：快任务的框架开销在高负载 2 核机上实测可达 20ms+，
    # 10ms 超时预算会让快任务也超时（历史上多次批跑抖动的根源）。
    adapter = ScenarioAdapter(
        lambda message: f"完成:{message}",
        delay_fn=lambda message: 1.0 if "慢任务" in message else 0.0,
    )
    plan = SimplePlan(tasks=[build_task("slow", "慢任务"), build_task("fast", "快任务")])

    result = await Orchestrator(
        adapter=adapter,
        parent_registry=ToolRegistry(),
        config=build_orchestrator_config(timeout=0.3),
    ).execute(plan)

    assert result.is_error is True
    assert "执行超时" in result.output
    assert "完成:快任务" in result.output
