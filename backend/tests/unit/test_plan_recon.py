from __future__ import annotations

import asyncio

from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStatus, PlanStore, TodoStore
from backend.core.s01_agent_loop.plan_recon import build_readonly_registry, is_readonly_bash
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json


def _runner(
    tmp_path, adapter: MockAdapter, registry: ToolRegistry | None = None
) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=registry or ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


def test_recon_runs_before_planning(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告: runner 实际结构", plan_json(step_count=1), "done"])
    runner = _runner(tmp_path, adapter)
    asyncio.run(runner.run("重构 runner"))
    assert "代码侦察员" in adapter.requests[0].messages[0].content
    assert "Plan & Execute 规划者" in adapter.requests[1].messages[0].content
    assert "侦察报告: runner 实际结构" in adapter.requests[1].messages[1].content


def test_recon_failure_degrades_gracefully(tmp_path) -> None:
    adapter = MockAdapter([RuntimeError("recon down"), plan_json(step_count=1), "done"])
    runner = _runner(tmp_path, adapter)
    asyncio.run(runner.run("重构 runner"))
    assert runner.status == PlanStatus.COMPLETED
    assert "侦察失败: recon down" in adapter.requests[1].messages[1].content


def test_recon_uses_readonly_tools(tmp_path) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry, str(tmp_path), mode="auto")
    readonly = build_readonly_registry(registry)
    names = {definition.name for definition in readonly.list_definitions()}
    assert {"Read", "Glob", "Grep", "Bash"}.issubset(names)
    assert "Write" not in names
    assert "str_replace" not in names
    assert "file_edit" not in names


def test_recon_readonly_bash_blocks_write(tmp_path) -> None:
    (tmp_path / "demo.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    register_builtin_tools(registry, str(tmp_path), mode="auto")
    readonly = build_readonly_registry(registry)
    tool = readonly.get("Bash")
    assert tool is not None
    _, execute = tool
    blocked = asyncio.run(execute({"command": "rm -rf /"}))
    allowed = asyncio.run(execute({"command": "cat demo.txt"}))
    assert blocked.is_error is True
    assert "禁止写操作" in blocked.output
    assert allowed.is_error is False
    assert allowed.output == "hello"
    assert is_readonly_bash("cat demo.txt")
    assert not is_readonly_bash("cat demo.txt > copy.txt")
