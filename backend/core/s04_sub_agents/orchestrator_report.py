from __future__ import annotations

from backend.common.errors import AgentError
from backend.common.types import ResolvedStage, SubAgentResult


def skip_result(stage_id: int, role_name: str, failed_deps: list[str]) -> SubAgentResult:
    deps = "、".join(failed_deps)
    return SubAgentResult(
        role=role_name,
        stage_id=stage_id,
        output=f"上游依赖 {deps} 失败，已跳过执行。",
        is_error=True,
    )


def coerce_result(
    stage_id: int,
    role_name: str,
    stage_result: SubAgentResult | Exception,
) -> SubAgentResult:
    if isinstance(stage_result, SubAgentResult):
        return stage_result.model_copy(update={"stage_id": stage_id})
    if isinstance(stage_result, AgentError):
        output = f"[{stage_result.code}] {stage_result.message}"
    else:
        output = str(stage_result)
    return SubAgentResult(role=role_name, stage_id=stage_id, output=output, is_error=True)


def format_report(
    stages: list[ResolvedStage],
    results: list[SubAgentResult],
    skipped_roles: set[str],
) -> str:
    """把多阶段子 agent 结果拼成给主 agent 消费的文本报告。"""
    skipped_count = sum(1 for item in results if item.role in skipped_roles)
    failed_count = sum(1 for item in results if item.is_error) - skipped_count
    summary = f"多 Agent 协作完成，共 {len(stages)} 个阶段，{len(results)} 个任务。"
    if failed_count:
        summary = f"{summary} 其中 {failed_count} 个子任务失败。"
    if skipped_count:
        summary = f"{summary} {skipped_count} 个子任务因上游失败被跳过。"
    sections = [summary]
    for stage in stages:
        role_line = ", ".join(stage.task_roles)
        sections.append(f"\n--- 阶段 {stage.stage_id}: {role_line} ---")
        for result in (item for item in results if item.stage_id == stage.stage_id):
            if result.role in skipped_roles:
                status = "跳过(上游失败)"
            else:
                status = "失败" if result.is_error else "完成"
            sections.append(f"\n[{result.role}] [{status}]")
            sections.append(result.output)
    return "\n".join(sections)


__all__ = ["coerce_result", "format_report", "skip_result"]
