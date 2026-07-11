from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from pathlib import Path
from uuid import uuid4

import pytest

from backend.adapters.base import LLMAdapter
from backend.api.routes.websocket_sub_agent import sub_agent_event_to_ws
from backend.common.types import AgentEvent, AgentTask, LLMRequest, LLMResponse, SimplePlan, StreamChunk, SubAgentResult
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import (
    AgentDefinitionLoader,
    Orchestrator,
    OrchestratorConfig,
    SpawnParams,
    SubAgentProgressEmitter,
    SubAgentSpawner,
)
from backend.core.s04_sub_agents.progress import clip_preview


@pytest.fixture(autouse=True)
def bind_test_database() -> Generator[None, None, None]:
    # 纯进程内逻辑，跳过 PostgresContainer。
    yield


class FakeAdapter(LLMAdapter):
    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="子任务已完成")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


def _collector() -> tuple[list[AgentEvent], object]:
    events: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        events.append(event)

    return events, handler


def _workspace() -> str:
    root = Path(__file__).resolve().parents[1] / ".tmp_sub_agents"
    root.mkdir(exist_ok=True)
    workspace = root / uuid4().hex
    workspace.mkdir()
    return str(workspace)


@pytest.mark.asyncio
async def test_orchestrator_emits_stage_and_agent_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events, handler = _collector()

    async def fake_run(run, runtime, on_event=None):  # noqa: ANN001
        role = run.task.role
        if role == "b":
            return SubAgentResult(role=role, stage_id=-1, output="炸了", is_error=True)
        return SubAgentResult(role=role, stage_id=-1, output=f"{role} 结果")

    monkeypatch.setattr("backend.core.s04_sub_agents.orchestrator.run_isolated_agent", fake_run)
    orchestrator = Orchestrator(
        adapter=FakeAdapter(),
        parent_registry=ToolRegistry(),
        config=OrchestratorConfig(workspace=_workspace(), default_model="m"),
        progress=SubAgentProgressEmitter(handler, "orchestrate", run_id="run-1"),
    )
    plan = SimplePlan(
        tasks=[
            AgentTask(role="a", task="做 a"),
            AgentTask(role="b", task="做 b"),
            AgentTask(role="c", task="汇总", depends_on=["a", "b"]),
        ]
    )
    result = await orchestrator.execute(plan)

    assert result.is_error is True  # b 失败 → 整体标错，c 被跳过
    types = [event.type for event in events]
    assert types.count("sub_agent_spawned") == 2  # 运行级 1 + 阶段0 1（阶段1 全跳过不发）
    overview = events[0].data
    assert overview["run_id"] == "run-1" and overview["source"] == "orchestrate"
    assert overview["total"] == 3 and overview["stage"] is None
    stage0 = next(e.data for e in events if e.type == "sub_agent_spawned" and e.data["stage"] == 0)
    assert sorted(stage0["specs"]) == ["a", "b"]
    done = [e for e in events if e.type in {"sub_agent_completed", "sub_agent_failed"}]
    assert {d.data["role"] for d in done} == {"a", "b", "c"}
    assert {d.data["completed"] for d in done} == {1, 2, 3}  # 实时递增计数
    skipped = next(d.data for d in done if d.data["role"] == "c")
    assert skipped["skipped"] is True and skipped["stage"] == 1
    failed_b = next(d for d in done if d.data["role"] == "b")
    assert failed_b.type == "sub_agent_failed" and "炸了" in failed_b.data["error"]


@pytest.mark.asyncio
async def test_dispatch_emits_spawned_progress_and_completed() -> None:
    events, handler = _collector()
    spawner = SubAgentSpawner(
        FakeAdapter(), ToolRegistry(), AgentDefinitionLoader(), "m", progress_handler=handler
    )
    result = await spawner.spawn_and_run(SpawnParams(role="helper", task="干活"))

    assert result.is_error is False
    types = [event.type for event in events]
    assert types[0] == "sub_agent_spawned"
    assert events[0].data["source"] == "dispatch" and events[0].data["specs"] == ["helper"]
    # 子 loop 的 assistant 消息经 child_observer 转成 sub_agent_progress
    progress = [e for e in events if e.type == "sub_agent_progress"]
    assert progress and progress[0].data["role"] == "helper"
    assert progress[0].data["kind"] == "message" and "子任务已完成" in progress[0].data["preview"]
    assert types[-1] == "sub_agent_completed"


@pytest.mark.asyncio
async def test_emitter_swallows_handler_errors() -> None:
    async def broken(event: AgentEvent) -> None:
        raise RuntimeError("handler 崩了")

    emitter = SubAgentProgressEmitter(broken, "dispatch")
    await emitter.spawned(total=1, specs=["x"], message="m")  # 不应抛出


def test_clip_preview_normalizes_and_truncates() -> None:
    assert clip_preview("  a\n  b\t c ") == "a b c"
    long = "x" * 500
    clipped = clip_preview(long)
    assert len(clipped) == 160 and clipped.endswith("…")


def test_ws_serialization_covers_all_sub_agent_types() -> None:
    spawned = sub_agent_event_to_ws(
        AgentEvent(
            type="sub_agent_spawned",
            data={"source": "orchestrate", "run_id": "r", "stage": 0, "total": 2,
                  "submitted": 2, "reused": 0, "specs": ["a", "b"], "message": "m"},
        )
    )
    assert spawned == {
        "type": "sub_agent_spawned", "source": "orchestrate", "run_id": "r", "stage": 0,
        "total": 2, "submitted": 2, "reused": 0, "specs": ["a", "b"], "message": "m",
    }
    progress = sub_agent_event_to_ws(
        AgentEvent(
            type="sub_agent_progress",
            data={"source": "dispatch", "run_id": "r", "stage": None, "role": "x",
                  "kind": "tool_call", "preview": "Read({...})"},
        )
    )
    assert progress is not None and progress["kind"] == "tool_call" and progress["role"] == "x"
    failed = sub_agent_event_to_ws(
        AgentEvent(
            type="sub_agent_failed",
            data={"source": "spawn", "run_id": "t", "spec_id": "s1", "completed": 1,
                  "total": 3, "error": "boom", "skipped": False, "message": "m"},
        )
    )
    assert failed is not None and failed["role"] == "s1" and failed["error"] == "boom"
    assert sub_agent_event_to_ws(AgentEvent(type="message", data={})) is None
