from __future__ import annotations

from dataclasses import dataclass

from backend.adapters.base import LLMAdapter
from backend.common.types.llm import LLMRequest
from backend.common.types.message import Message

from .plan_models import ExecutionPlan, PlanStep
from .plan_prompt import parse_plan_response
from .plan_task_routing import PlanRoute, PlanTaskKind


LIGHTWEIGHT_PLANNING_SYSTEM_PROMPT = """
你是 NeuralHub 的轻量任务规划者。用户任务不是代码仓库改造时，
你要直接规划业务执行步骤，不要进行代码侦察、源码读取或仓库分析。

必须输出纯 JSON，不要使用 markdown 代码块，不要添加解释文字。JSON 字段如下：
- goal: 一句话描述目标。
- approach: 分步骤的方法描述，类型为 list[str]。
- overall_summary: 规划摘要。
- risks: 风险列表。
- steps: 2-5 个执行步骤，每步包含 step_id, title, description, tools_hint。
- version: 可省略，默认 1。

规划要求：
- tools_hint 只能从可用工具列表中选择。
- 商品/优惠券/价格任务优先使用 product_search；需要网页补充时使用 WebSearch 或 browse_web。
- 资料/联网调研任务优先使用 WebSearch 或 browse_web。
- 只有用户要求保存报告、文件或 Markdown 时才把 Write 放进写报告步骤。
- 不要出现“读取代码”“侦察仓库”“分析源码”“检查 repo”之类步骤。
- 最后一步必须是“汇总并输出结果”，确保给用户可直接使用的业务输出。
""".strip()


@dataclass(frozen=True)
class LightweightPlanInput:
    adapter: LLMAdapter
    route: PlanRoute
    user_message: str
    tool_names: list[str]


async def generate_lightweight_plan(plan_input: LightweightPlanInput) -> ExecutionPlan:
    try:
        messages = build_lightweight_planning_messages(plan_input)
        request = LLMRequest(model="", messages=messages, temperature=0.2, max_tokens=4096)
        response = await plan_input.adapter.complete(request)
        plan = parse_plan_response(response.content)
        plan = _filter_unavailable_tools(plan, plan_input.tool_names)
        if _contains_repo_recon_step(plan):
            return fallback_lightweight_plan(plan_input, "轻量规划包含代码侦察步骤")
        return plan
    except Exception as exc:  # noqa: BLE001
        return fallback_lightweight_plan(plan_input, f"轻量规划失败: {exc}")


def build_lightweight_planning_messages(plan_input: LightweightPlanInput) -> list[Message]:
    tools = ", ".join(plan_input.tool_names or ["product_search", "WebSearch", "browse_web"])
    user_content = "\n".join(
        [
            f"任务类型：{plan_input.route.task_kind.value}",
            f"路由原因：{plan_input.route.reason}",
            f"用户任务：{plan_input.user_message}",
            f"可用工具列表：{tools}",
        ]
    )
    return [
        Message(role="system", content=LIGHTWEIGHT_PLANNING_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]


def fallback_lightweight_plan(plan_input: LightweightPlanInput, reason: str) -> ExecutionPlan:
    route = plan_input.route
    if route.task_kind == PlanTaskKind.COMMERCE_RESEARCH:
        return _commerce_plan(plan_input, reason)
    if route.task_kind == PlanTaskKind.WEB_RESEARCH:
        return _web_research_plan(plan_input, reason)
    return _general_plan(plan_input, reason)


def _commerce_plan(plan_input: LightweightPlanInput, reason: str) -> ExecutionPlan:
    search_tools = _preferred_tools(plan_input.tool_names, ["product_search", "WebSearch", "browse_web"])
    write_tools = _write_tools_if_requested(plan_input)
    steps = [
        PlanStep(
            step_id=1,
            title="搜索候选商品和优惠",
            description="围绕用户需求搜索商品、价格、优惠券和基础购买信息。",
            tools_hint=search_tools,
        ),
        PlanStep(
            step_id=2,
            title="筛选高性价比候选",
            description="按券后价、销量、店铺可信度和需求匹配度筛选可推荐商品。",
            tools_hint=search_tools,
        ),
        PlanStep(
            step_id=3,
            title="汇总并输出结果",
            description="输出推荐清单、价格/优惠说明、购买注意事项和无结果原因。",
            tools_hint=write_tools,
        ),
    ]
    return _plan(plan_input, reason, ("商品优惠调研计划", steps))


def _web_research_plan(plan_input: LightweightPlanInput, reason: str) -> ExecutionPlan:
    search_tools = _preferred_tools(plan_input.tool_names, ["WebSearch", "browse_web"])
    steps = [
        PlanStep(
            step_id=1,
            title="搜索权威资料",
            description="围绕用户问题检索近期资料、来源和关键事实。",
            tools_hint=search_tools,
        ),
        PlanStep(
            step_id=2,
            title="交叉核验信息",
            description="对比不同来源，保留可靠结论并标记不确定信息。",
            tools_hint=search_tools,
        ),
        PlanStep(
            step_id=3,
            title="汇总并输出结果",
            description="按用户要求输出清晰结论、推荐项和必要来源说明。",
            tools_hint=_write_tools_if_requested(plan_input),
        ),
    ]
    return _plan(plan_input, reason, ("联网调研计划", steps))


def _general_plan(plan_input: LightweightPlanInput, reason: str) -> ExecutionPlan:
    steps = [
        PlanStep(
            step_id=1,
            title="执行核心任务",
            description="直接围绕用户目标完成必要的信息整理或操作。",
            tools_hint=_preferred_tools(plan_input.tool_names, ["WebSearch", "browse_web"]),
        ),
        PlanStep(
            step_id=2,
            title="汇总并输出结果",
            description="用简洁结构给出最终结果、限制和后续建议。",
            tools_hint=_write_tools_if_requested(plan_input),
        ),
    ]
    return _plan(plan_input, reason, ("轻量任务计划", steps))


def _plan(
    plan_input: LightweightPlanInput,
    reason: str,
    payload: tuple[str, list[PlanStep]],
) -> ExecutionPlan:
    summary, steps = payload
    return ExecutionPlan(
        goal=plan_input.user_message.strip()[:120] or "执行用户任务",
        approach=[plan_input.route.reason, reason],
        overall_summary=f"{summary}：{plan_input.route.reason}",
        risks=["外部搜索或商品工具可能返回不完整结果，需要在输出中说明限制"],
        steps=steps,
    )


def _preferred_tools(available: list[str], preferred: list[str]) -> list[str]:
    names = [tool for tool in preferred if tool in available]
    return names or ([preferred[0]] if not available and preferred else [])


def _write_tools_if_requested(plan_input: LightweightPlanInput) -> list[str]:
    if "Write" not in plan_input.tool_names:
        return []
    markers = ("报告", "保存", "写入", "文件", "markdown", ".md")
    return ["Write"] if any(marker in plan_input.user_message.casefold() for marker in markers) else []


def _filter_unavailable_tools(plan: ExecutionPlan, tool_names: list[str]) -> ExecutionPlan:
    if not tool_names:
        return plan
    allowed = set(tool_names)
    for step in plan.steps:
        step.tools_hint = [tool for tool in step.tools_hint if tool in allowed]
    return plan


def _contains_repo_recon_step(plan: ExecutionPlan) -> bool:
    markers = ("读取代码", "侦察仓库", "分析源码", "检查 repo", "代码库")
    text = "\n".join(f"{step.title}\n{step.description}" for step in plan.steps).casefold()
    return any(marker in text for marker in markers)


__all__ = [
    "LIGHTWEIGHT_PLANNING_SYSTEM_PROMPT",
    "LightweightPlanInput",
    "build_lightweight_planning_messages",
    "fallback_lightweight_plan",
    "generate_lightweight_plan",
]
