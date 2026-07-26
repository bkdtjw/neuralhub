from __future__ import annotations

from typing import Any

import pytest

from backend.core.s02_tools.builtin.spawn_agent import create_spawn_agent_tool
from backend.core.s02_tools.builtin.spawn_agent_support import SpawnAgentDeps
from backend.core.s05_skills import AgentCategory, AgentSpec, SpecRegistry
from backend.core.s05_skills.models import SubAgentPolicy
from backend.core.task_queue import TaskPayload, TaskStatus


class FakeQueue:
    def __init__(
        self,
        plans: list[tuple[TaskStatus, str]] | None = None,
        children: list[TaskPayload] | None = None,
    ) -> None:
        self._plans = plans or []
        self._children = children or []
        self.submitted: list[dict[str, Any]] = []
        self._statuses: dict[str, TaskPayload] = {}

    async def submit(
        self,
        task_id: str,
        input_data: dict[str, Any],
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
    ) -> TaskPayload:
        plan = self._plans[len(self.submitted)]
        payload = TaskPayload(
            task_id=task_id,
            namespace="sub_agent",
            input_data=input_data,
            status=plan[0],
            created_at=0.0,
            timeout_seconds=timeout_seconds,
            result={"content": plan[1]} if plan[0] == TaskStatus.SUCCEEDED else None,
            error="" if plan[0] == TaskStatus.SUCCEEDED else plan[1],
            max_retries=max_retries,
        )
        self.submitted.append({"task_id": task_id, "input_data": input_data})
        self._statuses[task_id] = payload
        return payload

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]:
        _ = parent_task_id
        return self._children

    async def get_status(self, task_id: str) -> TaskPayload | None:
        return self._statuses.get(task_id)

    async def wait_for_tasks(
        self,
        task_ids: list[str],
        poll_interval: float = 0.5,
        global_timeout: float = 0.0,
    ) -> list[TaskPayload]:
        _ = poll_interval
        _ = global_timeout
        return [self._statuses[task_id] for task_id in task_ids]


def _registry() -> SpecRegistry:
    registry = SpecRegistry()
    registry.register(
        AgentSpec(id="code-reviewer", title="Code Reviewer", category=AgentCategory.CODING)
    )
    return registry


def _execute(queue: FakeQueue, policy: SubAgentPolicy):
    return create_spawn_agent_tool(
        SpawnAgentDeps(
            task_queue=queue,  # type: ignore[arg-type]
            spec_registry=_registry(),
            workspace="/workspace",
            parent_task_id="parent-1",
            sub_agent_policy=policy,
        )
    )[1]


@pytest.mark.asyncio
async def test_allowed_specs_enforced() -> None:
    # 配置了 spec 白名单时仍然收紧：名单外的 spec_id 被拒。
    queue = FakeQueue()
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"]))

    result = await execute({"tasks": [{"spec_id": "security-reviewer", "input": "audit"}]})

    assert result.is_error is True
    assert "未在白名单" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_free_inline_role_allowed_by_default() -> None:
    # 零配置即可自由起角色：缺省模板 generalist，readonly 下不带写类工具。
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    execute = _execute(queue, SubAgentPolicy())

    result = await execute({"tasks": [{"role": "报告审阅员", "input": "审阅本期报告"}]})

    assert result.is_error is False
    data = queue.submitted[0]["input_data"]
    assert data["template"] == "generalist"
    assert data["permission"] == "readonly"
    assert data["tools"] and all(tool not in {"Write", "Bash", "Edit"} for tool in data["tools"])


@pytest.mark.asyncio
async def test_empty_allowed_specs_allows_registered_spec() -> None:
    # 白名单为空 = 不限制：任意已注册 spec 直接放行。
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    execute = _execute(queue, SubAgentPolicy())

    result = await execute({"tasks": [{"spec_id": "code-reviewer", "input": "review"}]})

    assert result.is_error is False
    assert queue.submitted[0]["input_data"]["spec_id"] == "code-reviewer"


@pytest.mark.asyncio
async def test_explicit_inline_tools_override_template_tools() -> None:
    # 显式请求的工具即为准，不再与模板工具集求交。
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    execute = _execute(queue, SubAgentPolicy())

    result = await execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "template": "code-reader",
                    "tools": ["WebSearch"],
                    "input": "调研",
                }
            ]
        }
    )

    assert result.is_error is False
    assert queue.submitted[0]["input_data"]["tools"] == ["WebSearch"]


@pytest.mark.asyncio
async def test_max_concurrent_enforced() -> None:
    active = TaskPayload(
        task_id="running-1",
        namespace="sub_agent",
        input_data={},
        status=TaskStatus.RUNNING,
        created_at=0.0,
    )
    queue = FakeQueue(children=[active])
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"], max_concurrent=1))

    result = await execute({"tasks": [{"spec_id": "code-reviewer", "input": "review"}]})

    assert result.is_error is True
    assert "并发超过上限" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_readonly_strips_write_tools() -> None:
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"]))

    result = await execute(
        {
            "tasks": [
                {
                    "spec_id": "code-reviewer",
                    "tools": ["Read", "Write", "Bash", "str_replace"],
                    "input": "audit without writes",
                }
            ]
        }
    )

    assert result.is_error is False
    assert queue.submitted[0]["input_data"]["permission"] == "readonly"
    assert queue.submitted[0]["input_data"]["tools"] == ["Read"]


@pytest.mark.asyncio
async def test_readonly_strips_write_tools_case_insensitive() -> None:
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"]))

    result = await execute(
        {
            "tasks": [
                {
                    "spec_id": "code-reviewer",
                    "tools": ["Read", "write", "bash", "Apply_Patch", "Grep"],
                    "input": "audit without writes",
                }
            ]
        }
    )

    assert result.is_error is False
    assert queue.submitted[0]["input_data"]["tools"] == ["Read", "Grep"]


@pytest.mark.asyncio
async def test_reuse_key_includes_permission() -> None:
    existing = TaskPayload(
        task_id="old-writable",
        namespace="sub_agent",
        input_data={
            "spec_id": "code-reviewer",
            "role": "",
            "system_prompt": "",
            "tools": ["Read"],
            "input": "same input",
            "permission": "writable",
            "workspace": "/workspace",
        },
        status=TaskStatus.SUCCEEDED,
        created_at=0.0,
        result={"content": "old"},
    )
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "new")], children=[existing])
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"]))

    result = await execute(
        {
            "tasks": [
                {
                    "spec_id": "code-reviewer",
                    "tools": ["Read"],
                    "permission": "readonly",
                    "input": "same input",
                }
            ]
        }
    )

    assert result.is_error is False
    assert len(queue.submitted) == 1
    assert "new" in result.output
