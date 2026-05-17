from __future__ import annotations

from backend.common.types import AgentConfig, AgentEvent, ToolResult
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s01_agent_loop.plan_execute_runner_steps import ConvergenceMonitor
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter


def _monitor() -> tuple[AgentLoop, ConvergenceMonitor]:
    loop = AgentLoop(AgentConfig(model="test"), MockAdapter(), ToolRegistry())
    return loop, ConvergenceMonitor(loop, "读取目标文件")


def _tool_result(index: int) -> AgentEvent:
    return AgentEvent(type="tool_result", data=ToolResult(tool_call_id=f"tc{index}", output="ok"))


def _flush_event() -> AgentEvent:
    return AgentEvent(type="status_change", data="thinking")


def test_convergence_prompt_injected_at_threshold() -> None:
    loop, monitor = _monitor()
    for index in range(5):
        monitor.on_event(_tool_result(index))
    monitor.on_event(_flush_event())
    assert any("[系统提醒]" in message.content for message in loop.messages)


def test_convergence_escalation() -> None:
    loop, monitor = _monitor()
    for index in range(10):
        monitor.on_event(_tool_result(index))
    monitor.on_event(_flush_event())
    content = "\n".join(message.content for message in loop.messages)
    assert "[系统提醒]" in content
    assert "[系统警告]" in content
    assert "[系统强制]" in content


def test_no_convergence_prompt_under_threshold() -> None:
    loop, monitor = _monitor()
    for index in range(3):
        monitor.on_event(_tool_result(index))
    monitor.on_event(_flush_event())
    assert not any("[系统提醒]" in message.content for message in loop.messages)
