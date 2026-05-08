from __future__ import annotations

from .plan_models import PlanStep

STEP_EXECUTION_SYSTEM_PROMPT = """
你是 Agent Studio 的计划执行者。你只执行当前步骤，不重新规划整个任务。
当前步骤是第 {step_index}/{total_steps} 步。
标题：{title}
描述：{description}
工作区：{workspace}

执行要求：
1. 聚焦当前步骤，必要时使用工具读取、修改或验证。
2. 如果前一步摘要提供了上下文，必须据此调整操作。
3. 如发现后续计划明显不适配，使用 TodoUpdate 调整未执行步骤。
4. 输出要简洁说明完成内容、关键发现、涉及文件和未解决风险。
5. 不要声称完成没有实际执行的操作。

收敛要求：
- 当前步骤应尽量在 5 次工具调用内完成。
- 不要扩大搜索范围；已有信息足够时立即输出结论。
- 收到 [系统提醒]、[系统警告] 或 [系统强制] 后，必须优先结束当前步骤。

前一步摘要：
{previous_summary}
""".strip()

CONVERGENCE_PROMPTS = {
    5: (
        "[系统提醒] 你已使用 {n} 次工具调用。"
        "请回顾当前步骤的目标：\n\n{step_goal}\n\n"
        "如果已收集足够信息，请立即给出结论。不要继续扩大搜索范围。"
    ),
    8: (
        "[系统警告] 你已使用 {n} 次工具调用，接近上限。"
        "当前步骤目标：{step_goal}\n\n"
        "你必须在接下来 2 次工具调用内完成本步骤。"
        "立即基于已有信息给出结论，即使信息不完整。"
    ),
    10: (
        "[系统强制] 你已使用 {n} 次工具调用。"
        "当前步骤目标：{step_goal}\n\n"
        "这是最后一次提醒。下一轮你必须直接输出结论，不再调用任何工具。"
        "基于已收集的信息总结结果。"
    ),
}
CONVERGENCE_THRESHOLDS = sorted(CONVERGENCE_PROMPTS.keys())


def build_step_messages(
    step: PlanStep,
    step_index: int,
    total_steps: int,
    previous_summary: str = "",
    workspace: str = "",
) -> tuple[str, str]:
    summary = previous_summary.strip() or "无"
    system_prompt = STEP_EXECUTION_SYSTEM_PROMPT.format(
        step_index=step_index,
        total_steps=total_steps,
        title=step.title,
        description=step.description,
        workspace=workspace or "当前项目工作区",
        previous_summary=summary,
    )
    user_message = "\n".join(
        [
            f"请执行计划第 {step_index}/{total_steps} 步：{step.title}",
            "",
            step.description,
            "",
            f"前一步摘要：{summary}",
        ]
    )
    return system_prompt, user_message


__all__ = [
    "CONVERGENCE_PROMPTS",
    "CONVERGENCE_THRESHOLDS",
    "STEP_EXECUTION_SYSTEM_PROMPT",
    "build_step_messages",
]
