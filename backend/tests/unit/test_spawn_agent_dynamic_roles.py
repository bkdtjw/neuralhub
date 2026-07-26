from __future__ import annotations

from typing import Any

import pytest

from backend.core.s02_tools.builtin.spawn_agent import create_spawn_agent_tool
from backend.core.s02_tools.builtin.spawn_agent_support import SpawnAgentDeps
from backend.core.s05_skills import SpecRegistry
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

    async def submit(self, task_id: str, input_data: dict[str, Any], **kwargs: Any) -> TaskPayload:
        plan = self._plans[len(self.submitted)]
        payload = TaskPayload(
            task_id=task_id,
            namespace="sub_agent",
            input_data=input_data,
            status=plan[0],
            created_at=0.0,
            result={"content": plan[1]} if plan[0] == TaskStatus.SUCCEEDED else None,
            error="" if plan[0] == TaskStatus.SUCCEEDED else plan[1],
            timeout_seconds=float(kwargs.get("timeout_seconds", 60.0)),
        )
        self.submitted.append({"task_id": task_id, "input_data": input_data})
        self._statuses[task_id] = payload
        return payload

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]:
        _ = parent_task_id
        return self._children

    async def get_status(self, task_id: str) -> TaskPayload | None:
        return self._statuses.get(task_id)

    async def wait_for_tasks(self, task_ids: list[str], **_: Any) -> list[TaskPayload]:
        return [self._statuses[task_id] for task_id in task_ids]


def _policy() -> SubAgentPolicy:
    return SubAgentPolicy(
        allow_inline_roles=True,
        allowed_inline_templates=["research-specialist", "code-reader"],
        allowed_inline_tools=["WebSearch", "browse_web", "read_history", "Read"],
        max_iterations_default=9,
        max_iterations_cap=15,
    )


def _tool(queue: FakeQueue):
    return create_spawn_agent_tool(
        SpawnAgentDeps(
            task_queue=queue,  # type: ignore[arg-type]
            spec_registry=SpecRegistry(),
            workspace="/workspace",
            parent_task_id="parent-1",
            sub_agent_policy=_policy(),
        )
    )


def test_schema_exposes_dynamic_template_and_budget() -> None:
    definition, _ = _tool(FakeQueue())
    task_props = definition.parameters.properties["tasks"]["items"]["properties"]

    assert "template" in task_props
    assert "max_iterations" in task_props
    assert "permission" in task_props
    assert "no_cache" in task_props
    assert "depends_on" in task_props
    assert "on_dep_failure" in task_props
    assert "required" in task_props


@pytest.mark.asyncio
async def test_dynamic_role_uses_template_prompt_tools_and_budget_cap() -> None:
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    _, execute = _tool(queue)

    result = await execute(
        {
            "tasks": [
                {
                    "role": "字节研究员",
                    "template": "research-specialist",
                    "system_prompt": "只关注 AI 产品",
                    "tools": ["WebSearch", "Read"],
                    "max_iterations": 99,
                    "input": "调研字节跳动",
                }
            ]
        }
    )

    data = queue.submitted[0]["input_data"]
    assert result.is_error is False
    assert data["role"] == "字节研究员"
    assert data["template"] == "research-specialist"
    # 显式请求的工具即为准（Read 在策略白名单内，不再被模板集吞掉）
    assert data["tools"] == ["WebSearch", "Read"]
    assert data["max_iterations"] == 15
    assert "只读研究员" in str(data["system_prompt"])
    assert "动态角色：字节研究员" in str(data["system_prompt"])
    assert "补充约束：只关注 AI 产品" in str(data["system_prompt"])


@pytest.mark.asyncio
async def test_dynamic_role_rejects_unknown_template_before_submit() -> None:
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    _, execute = _tool(queue)

    result = await execute(
        {"tasks": [{"role": "阿里研究员", "template": "unknown", "input": "调研阿里"}]}
    )

    assert result.is_error is True
    assert "template 未被允许" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_dynamic_role_default_template_rejected_when_templates_configured() -> None:
    # 缺省 template 回退 generalist；策略配置了模板白名单且不含 generalist 时仍拒绝。
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "done")])
    _, execute = _tool(queue)

    result = await execute({"tasks": [{"role": "阿里研究员", "input": "调研阿里"}]})

    assert result.is_error is True
    assert "template 未被允许: generalist" in result.output
    assert queue.submitted == []


@pytest.mark.parametrize(
    ("existing_template", "existing_budget", "new_template", "new_budget"),
    [
        ("code-reader", 6, "research-specialist", 6),
        ("research-specialist", 5, "research-specialist", 6),
    ],
)
@pytest.mark.asyncio
async def test_dynamic_role_reuse_key_includes_template_and_budget(
    existing_template: str,
    existing_budget: int,
    new_template: str,
    new_budget: int,
) -> None:
    existing = TaskPayload(
        task_id="old",
        namespace="sub_agent",
        input_data={
            "role": "字节研究员",
            "template": existing_template,
            "input": "same",
            "tools": ["read_history"],
            "permission": "readonly",
            "max_iterations": existing_budget,
            "workspace": "/workspace",
        },
        status=TaskStatus.SUCCEEDED,
        created_at=0.0,
        result={"content": "old"},
    )
    queue = FakeQueue([(TaskStatus.SUCCEEDED, "new")], children=[existing])
    _, execute = _tool(queue)

    result = await execute(
        {
            "tasks": [
                {
                    "role": "字节研究员",
                    "template": new_template,
                    "tools": ["read_history"],
                    "permission": "readonly",
                    "max_iterations": new_budget,
                    "input": "same",
                }
            ]
        }
    )

    assert result.is_error is False
    assert len(queue.submitted) == 1
    assert "new" in result.output
