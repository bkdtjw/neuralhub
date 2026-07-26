from __future__ import annotations

from typing import Any

import pytest

from backend.core.s02_tools.builtin.spawn_agent import create_spawn_agent_tool
from backend.core.s02_tools.builtin.spawn_agent_support import SpawnAgentDeps
from backend.core.s05_skills import AgentCategory, AgentSpec, SpecRegistry
from backend.core.s05_skills.models import SubAgentPolicy


class FakeQueue:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    async def submit(self, task_id: str, input_data: dict[str, Any], **_: Any) -> object:
        self.submitted.append({"task_id": task_id, "input_data": input_data})
        return object()

    async def get_children(self, parent_task_id: str) -> list[object]:
        _ = parent_task_id
        return []


def _registry() -> SpecRegistry:
    registry = SpecRegistry()
    for spec_id in ["code-reviewer", "security-reviewer"]:
        registry.register(AgentSpec(id=spec_id, title=spec_id, category=AgentCategory.CODING))
    return registry


def _execute(queue: FakeQueue, policy: SubAgentPolicy):
    return create_spawn_agent_tool(
        SpawnAgentDeps(
            task_queue=queue,  # type: ignore[arg-type]
            spec_registry=_registry(),
            workspace="/workspace",
            sub_agent_policy=policy,
        )
    )[1]


@pytest.mark.asyncio
async def test_registered_spec_rejected_when_not_policy_allowed() -> None:
    queue = FakeQueue()
    execute = _execute(queue, SubAgentPolicy(allowed_specs=["code-reviewer"]))

    result = await execute({"tasks": [{"spec_id": "security-reviewer", "input": "audit"}]})

    assert result.is_error is True
    assert "未在白名单" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_inline_default_template_rejected_when_templates_configured() -> None:
    # 配置了模板白名单且不含缺省 generalist 时，未声明 template 的 inline 角色仍被拒。
    queue = FakeQueue()
    execute = _execute(
        queue,
        SubAgentPolicy(
            allowed_specs=["security-reviewer"],
            allow_inline_roles=True,
            allowed_inline_templates=["code-reviewer"],
        ),
    )

    result = await execute({"tasks": [{"role": "security-reviewer", "input": "audit"}]})

    assert result.is_error is True
    assert "template 未被允许" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_inline_tools_outside_policy_whitelist_rejected() -> None:
    # allowed_inline_tools 配置了才收紧：请求名单外工具直接在治理层拒绝。
    queue = FakeQueue()
    execute = _execute(
        queue,
        SubAgentPolicy(
            allow_inline_roles=True,
            allowed_inline_templates=["research-specialist"],
            allowed_inline_tools=["Read"],
        ),
    )

    result = await execute(
        {
            "tasks": [
                {
                    "role": "研究员",
                    "template": "research-specialist",
                    "tools": ["WebSearch"],
                    "input": "调研",
                }
            ]
        }
    )

    assert result.is_error is True
    assert "工具不在允许范围" in result.output
    assert queue.submitted == []


@pytest.mark.asyncio
async def test_inline_role_disabled_by_policy() -> None:
    # allow_inline_roles=False 仍可显式关掉自由角色。
    queue = FakeQueue()
    execute = _execute(queue, SubAgentPolicy(allow_inline_roles=False))

    result = await execute({"tasks": [{"role": "研究员", "input": "调研"}]})

    assert result.is_error is True
    assert "已禁用动态角色" in result.output
    assert queue.submitted == []
