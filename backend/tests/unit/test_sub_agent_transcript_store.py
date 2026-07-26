"""转录存储 + 进度发射器全文记录：preview 截断上 WS，全文进存储。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.common.types import AgentEvent
from backend.core.s04_sub_agents import SubAgentProgressEmitter, SubAgentTranscriptStore


def _tool_result_event(output: str, is_error: bool = False) -> AgentEvent:
    return AgentEvent(type="tool_result", data=SimpleNamespace(output=output, is_error=is_error))


def test_record_entry_ring_buffer_and_clip() -> None:
    store = SubAgentTranscriptStore(max_runs=4, max_entries_per_agent=2, max_entry_chars=10)
    for index in range(3):
        store.record_entry("run1", "dispatch", "coder", "message", f"内容{index}-" + "x" * 20)
    agent = store.get_agent("run1", "coder")
    assert agent is not None
    assert len(agent.entries) == 2
    assert agent.dropped == 1
    assert all(len(entry.content) == 10 and entry.content.endswith("…") for entry in agent.entries)
    assert agent.entries[-1].content.startswith("内容2")


def test_lru_evicts_oldest_run() -> None:
    store = SubAgentTranscriptStore(max_runs=2)
    for run_id in ("run1", "run2", "run3"):
        store.record_entry(run_id, "dispatch", "coder", "message", "hi")
    assert store.get_run("run1") is None
    assert [summary.run_id for summary in store.list_runs()] == ["run3", "run2"]


def test_orchestrate_roster_stays_pending_until_stage_starts() -> None:
    store = SubAgentTranscriptStore()
    store.record_spawned("run1", "orchestrate", ["researcher", "writer"], message="编排启动")
    assert store.get_agent("run1", "writer").status == "pending"
    store.record_spawned("run1", "orchestrate", ["researcher"], stage=1)
    assert store.get_agent("run1", "researcher").status == "running"
    assert store.get_agent("run1", "researcher").stage == 1
    assert store.get_run("run1").message == "编排启动"


def test_record_done_statuses() -> None:
    store = SubAgentTranscriptStore()
    store.record_done("run1", "orchestrate", "ok-agent")
    store.record_done("run1", "orchestrate", "bad-agent", error="boom")
    store.record_done("run1", "orchestrate", "skip-agent", skipped=True)
    assert store.get_agent("run1", "ok-agent").status == "done"
    assert store.get_agent("run1", "bad-agent").status == "failed"
    assert store.get_agent("run1", "bad-agent").error == "boom"
    assert store.get_agent("run1", "skip-agent").status == "skipped"


@pytest.mark.asyncio
async def test_child_observer_records_full_content_and_clips_preview() -> None:
    store = SubAgentTranscriptStore()
    events: list[AgentEvent] = []
    emitter = SubAgentProgressEmitter(events.append, "dispatch", store=store)
    observer = emitter.child_observer("coder")
    long_output = "输出片段-" + "y" * 500

    await observer(_tool_result_event(long_output))
    await observer(AgentEvent(type="tool_call", data=SimpleNamespace(name="bash", arguments={"cmd": "ls"})))
    await observer(AgentEvent(type="status_change", data=None))  # 非转发类型：忽略

    agent = store.get_agent(emitter.run_id, "coder")
    assert agent is not None
    assert [entry.kind for entry in agent.entries] == ["tool_result", "tool_call"]
    assert agent.entries[0].content == long_output  # 全文，不截 160
    assert agent.entries[1].content == "bash({'cmd': 'ls'})"
    assert len(events) == 2
    assert len(events[0].data["preview"]) <= 160


@pytest.mark.asyncio
async def test_child_observer_marks_tool_errors() -> None:
    store = SubAgentTranscriptStore()
    events: list[AgentEvent] = []
    emitter = SubAgentProgressEmitter(events.append, "dispatch", store=store)
    await emitter.child_observer("coder")(_tool_result_event("失败原因", is_error=True))
    entry = store.get_agent(emitter.run_id, "coder").entries[0]
    assert entry.is_error is True
    assert entry.content == "失败原因"
    assert events[0].data["preview"].startswith("✗ ")


@pytest.mark.asyncio
async def test_lifecycle_recorded_via_emitter() -> None:
    store = SubAgentTranscriptStore()
    emitter = SubAgentProgressEmitter(None, "orchestrate", store=store)
    await emitter.spawned(total=2, specs=["a", "b"], message="启动")
    await emitter.agent_done(role="a", completed=1, total=2, message="done", stage=1)
    await emitter.agent_done(role="b", completed=2, total=2, message="fail", stage=1, error="err")
    run = store.get_run(emitter.run_id)
    assert run is not None and run.order == ["a", "b"]
    assert run.agents["a"].status == "done"
    assert run.agents["b"].status == "failed"


@pytest.mark.asyncio
async def test_store_failure_never_blocks_progress() -> None:
    class BrokenStore:
        def record_entry(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("store down")

    events: list[AgentEvent] = []
    emitter = SubAgentProgressEmitter(events.append, "dispatch", store=BrokenStore())  # type: ignore[arg-type]
    await emitter.child_observer("coder")(_tool_result_event("正常输出"))
    assert len(events) == 1  # 存储炸了也不影响 preview 转发
