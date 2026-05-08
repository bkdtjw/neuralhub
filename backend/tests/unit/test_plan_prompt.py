from __future__ import annotations

import pytest

from backend.core.s01_agent_loop import (
    PlanParseError,
    build_planning_messages,
    parse_plan_response,
)
from backend.tests.unit.plan_execute_test_support import VALID_PLAN_JSON


def test_parse_plan_response_valid_json() -> None:
    plan = parse_plan_response(VALID_PLAN_JSON)
    assert plan.goal == "LLM生成的目标"
    assert len(plan.steps) == 3


def test_parse_plan_response_json_in_code_block() -> None:
    content = f"好的，以下是计划：\n```json\n{VALID_PLAN_JSON}\n```\n希望有帮助"
    plan = parse_plan_response(content)
    assert plan.goal == "LLM生成的目标"


def test_parse_plan_response_json_with_preamble() -> None:
    content = f"好的，以下是计划：\n{VALID_PLAN_JSON}\n希望这个计划能帮到你"
    plan = parse_plan_response(content)
    assert plan.steps[0].title == "分析"


def test_parse_plan_response_invalid() -> None:
    with pytest.raises(PlanParseError):
        parse_plan_response("这不是 JSON，也没有任何结构化内容。")


def test_parse_plan_response_empty_steps() -> None:
    with pytest.raises(PlanParseError):
        parse_plan_response('{"goal":"test","approach":["a"],"data_structures":"","steps":[]}')


def test_build_planning_messages() -> None:
    messages = build_planning_messages("重构 s07", tool_names=["Read", "Write", "Bash"])
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "Read" in messages[0].content
    assert "重构 s07" in messages[1].content


def test_build_planning_messages_with_recon_report() -> None:
    messages = build_planning_messages("重构 s07", ["Read"], recon_report="实际读取了 runner")
    assert "## 用户任务" in messages[1].content
    assert "## 侦察报告" in messages[1].content
    assert "实际读取了 runner" in messages[1].content
