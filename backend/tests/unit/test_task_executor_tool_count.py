from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.common.types import Message, ToolCall, ToolResult
from backend.core.s07_task_system import TaskExecutor, TaskExecutorDeps
from backend.core.s07_task_system.models import NotifyConfig, OutputConfig, ScheduledTask


def _task() -> ScheduledTask:
    return ScheduledTask(
        name="AI日报",
        prompt="generate report",
        notify=NotifyConfig(feishu=False),
        output=OutputConfig(save_markdown=False),
    )


@pytest.mark.asyncio
async def test_execute_counts_sub_agent_tool_calls_in_meta() -> None:
    agent = SimpleNamespace(
        _config=SimpleNamespace(model="test-model", provider="provider-1"),
        messages=[
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(name="spawn_agent", arguments={"tasks": []}),
                    ToolCall(name="failing_tool", arguments={}),
                ],
            ),
            Message(
                role="tool",
                content="",
                tool_results=[
                    ToolResult(output="ok\n[meta] sub_agent_tool_calls=4"),
                    ToolResult(output="failed", is_error=True),
                ],
            ),
        ],
        run=AsyncMock(return_value=Message(role="assistant", content="final report")),
    )
    executor = TaskExecutor(
        TaskExecutorDeps.model_construct(provider_manager=AsyncMock(), mcp_manager=AsyncMock())
    )

    with (
        patch.object(executor, "_create_loop", new=AsyncMock(return_value=(agent, object()))),
        patch.object(
            executor,
            "_save_report",
            new=AsyncMock(return_value=Path("/tmp/report.md")),
        ) as mock_save,
        patch.object(executor, "_persist_session", new=AsyncMock()),
    ):
        result = await executor.execute(_task())

    assert result == "final report"
    assert mock_save.await_args.args[2]["tool_call_count"] == 6
    assert mock_save.await_args.args[2]["success_count"] == 1
