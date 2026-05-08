from __future__ import annotations

import json
import re
from typing import Any

from backend.common.errors import AgentError
from backend.common.types.message import Message

from .plan_models import ExecutionPlan

PLANNING_SYSTEM_PROMPT = """
你是 Agent Studio 的 Plan & Execute 规划者。你的任务是把用户需求拆成可执行计划，
供后续执行器逐步完成。你只负责规划，不执行工具，不调用外部系统。

必须输出纯 JSON，不要使用 markdown 代码块，不要添加解释文字。JSON 字段如下：
- goal: 一句话描述目标。
- approach: 分步骤的方法描述，类型为 list[str]。
- data_structures: 涉及的数据结构或模块设计，类型为 str，可为空字符串。
- steps: 执行步骤列表，每步包含 step_id, title, description, tools_hint。
- version: 可省略，默认 1。

	规划要求：
	- step_id 从 1 开始连续递增。
	- tools_hint 只能从可用工具列表中选择，例如 Read、Write、Bash、Glob、Grep。
	- 步骤数量保持在 3-8 步，不要过细也不要过粗。
	- 每个 description 必须足够具体，让执行者不依赖额外上下文也能理解要做什么。
	- 不要在计划中记录执行过程、结果或假设已经完成的事项。
	- 每步只做一件具体的事，不超过 5 次工具调用可完成。
	- 禁止出现“分析所有”“检查全部”这种模糊步骤。
	- 如果需要“搜索 + 分析 + 实施”，拆成独立步骤。
	- 侦察报告中已经分析过的内容，不要在步骤中重复分析。
	- 最后一步必须是“汇总并输出结果”，确保有明确的业务输出。

示例输出：
{
  "goal": "重构任务调度模块并保持现有行为",
  "approach": ["读取现有实现", "梳理依赖边界", "拆分并验证"],
  "data_structures": "保留 ScheduledTask，新增内部执行参数模型",
  "steps": [
    {
      "step_id": 1,
      "title": "读取调度模块",
      "description": "读取任务调度相关文件，确认公开接口和调用方。",
      "tools_hint": ["Read", "Grep"]
    }
  ],
  "version": 1
}
""".strip()

_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class PlanParseError(AgentError):
    """Raised when an LLM planning response cannot be parsed."""

    def __init__(self, message: str) -> None:
        super().__init__(code="PLAN_PARSE_ERROR", message=message)


def build_planning_messages(
    user_message: str,
    tool_names: list[str] | None = None,
    recon_report: str = "",
) -> list[Message]:
    tools = ", ".join(tool_names or ["Read", "Write", "Bash", "Glob", "Grep"])
    system_content = f"{PLANNING_SYSTEM_PROMPT}\n\n可用工具列表：{tools}"
    user_content = _planning_user_content(user_message, recon_report)
    return [
        Message(role="system", content=system_content),
        Message(role="user", content=user_content),
    ]


def _planning_user_content(user_message: str, recon_report: str) -> str:
    report = recon_report.strip()
    if not report:
        return user_message
    return "\n".join(
        [
            "## 用户任务",
            user_message,
            "",
            "## 侦察报告",
            "以下是对项目的实际分析结果，请基于这些事实制定计划：",
            "",
            report,
        ]
    )


def parse_plan_response(content: str) -> ExecutionPlan:
    errors: list[str] = []
    for candidate in _json_candidates(content):
        try:
            data = json.loads(candidate)
            return _validate_plan(data)
        except PlanParseError as exc:
            errors.append(exc.message)
        except json.JSONDecodeError as exc:
            errors.append(f"JSON parse failed at {exc.pos}: {exc.msg}")
    detail = "; ".join(errors) if errors else "No JSON object found"
    raise PlanParseError(f"Unable to parse execution plan: {detail}")


def _json_candidates(content: str) -> list[str]:
    candidates = [content.strip()]
    code_block = _extract_code_block(content)
    if code_block:
        candidates.append(code_block)
    object_block = _extract_first_json_object(content)
    if object_block:
        candidates.append(object_block)
    return [candidate for candidate in candidates if candidate]


def _extract_code_block(content: str) -> str:
    match = _CODE_BLOCK_RE.search(content)
    return match.group(1).strip() if match else ""


def _extract_first_json_object(content: str) -> str:
    start = content.find("{")
    while start >= 0:
        block = _balanced_object_at(content, start)
        if block:
            return block
        start = content.find("{", start + 1)
    return ""


def _balanced_object_at(content: str, start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return ""


def _validate_plan(data: Any) -> ExecutionPlan:
    if not isinstance(data, dict):
        raise PlanParseError("Plan response root must be a JSON object")
    normalized = dict(data)
    normalized.setdefault("goal", "")
    normalized.setdefault("approach", [])
    normalized.setdefault("data_structures", "")
    normalized.setdefault("version", 1)
    if not normalized.get("steps"):
        raise PlanParseError("Plan response must contain at least one step")
    try:
        return ExecutionPlan.model_validate(normalized)
    except Exception as exc:  # noqa: BLE001
        raise PlanParseError(str(exc)) from exc


__all__ = [
    "PLANNING_SYSTEM_PROMPT",
    "PlanParseError",
    "build_planning_messages",
    "parse_plan_response",
]
