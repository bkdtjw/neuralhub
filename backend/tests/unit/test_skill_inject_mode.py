from __future__ import annotations

import json

import pytest

from backend.common.types import AgentConfig, Message
from backend.core.s01_agent_loop.agent_loop_support import build_llm_request
from backend.core.s02_tools.builtin.load_skill import create_load_skill_tool
from backend.core.s05_skills import AgentCategory, AgentSpec, OnDemandSkillLoader, SpecRegistry


def _registry() -> SpecRegistry:
    registry = SpecRegistry()
    registry.register(
        AgentSpec(
            id="feishu-card-format",
            title="Feishu card format",
            category=AgentCategory.DOCUMENT,
            system_prompt="card format rules",
            mode="inject",
            trigger_keywords=["card"],
        )
    )
    registry.register(
        AgentSpec(
            id="lingxi-ranklist-skill",
            title="Lingxi ranklist",
            category=AgentCategory.RESEARCH,
            system_prompt="ranklist executor",
        )
    )
    return registry


def test_inject_skill_matches_into_zone2() -> None:
    loader = OnDemandSkillLoader(_registry())
    request = build_llm_request(
        AgentConfig(model="model", system_prompt="stable"),
        [Message(role="system", content="stable"), Message(role="user", content="make a card")],
        [],
        skill_loader=loader,
    )

    assert [message.content for message in request.skill_messages] == ["card format rules"]
    assert request.system_prompt == "stable"


@pytest.mark.asyncio
async def test_load_skill_injects_once_on_next_request() -> None:
    loader = OnDemandSkillLoader(_registry())
    _, execute = create_load_skill_tool(loader)

    result = await execute({"skill_id": "feishu-card-format"})
    request = build_llm_request(
        AgentConfig(model="model", system_prompt="stable"),
        [Message(role="user", content="no trigger")],
        [],
        skill_loader=loader,
    )
    next_request = build_llm_request(
        AgentConfig(model="model", system_prompt="stable"),
        [Message(role="user", content="no trigger")],
        [],
        skill_loader=loader,
    )

    assert json.loads(result.output)["injected"] is True
    assert [message.content for message in request.skill_messages] == ["card format rules"]
    assert next_request.skill_messages == []


@pytest.mark.asyncio
async def test_load_skill_loop_mode_does_not_inject_main_context() -> None:
    loader = OnDemandSkillLoader(_registry())
    _, execute = create_load_skill_tool(loader)

    result = await execute({"skill_id": "lingxi-ranklist-skill"})
    request = build_llm_request(
        AgentConfig(model="model", system_prompt="stable"),
        [Message(role="user", content="rank list")],
        [],
        skill_loader=loader,
    )

    payload = json.loads(result.output)
    assert payload["mode"] == "loop"
    assert payload["injected"] is False
    assert request.skill_messages == []
