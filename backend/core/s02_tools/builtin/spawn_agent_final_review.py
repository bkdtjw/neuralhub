from __future__ import annotations

from backend.common.metrics import incr
from backend.core.task_queue import (
    CapacitySubmitRequest,
    QueueSubmitSpec,
    TaskPayload,
    TaskStatus,
)

from .spawn_agent_governance import validate_dispatch_capacity
from .spawn_agent_prepare import prepare_tasks
from .spawn_agent_support import (
    PreparedTask,
    SpawnAgentDeps,
    SpawnAgentTask,
    emit_event,
    format_result,
)
from .spawn_agent_wait import wait_for_prepared_tasks

FINAL_REVIEW_TEMPLATE = "final-reviewer"
FINAL_REVIEW_ROLE = "最终发布审核专家"


async def run_final_review_if_needed(
    prepared: list[PreparedTask],
    statuses: list[TaskPayload],
    deps: SpawnAgentDeps,
) -> tuple[list[PreparedTask], list[TaskPayload]]:
    if not should_run_final_review(prepared, statuses, deps):
        return [], []
    review_prepared = prepare_tasks([build_final_review_task(prepared, statuses)], deps)
    await _submit_final_review(review_prepared, deps)
    await emit_event(
        deps.event_handler,
        "sub_agent_spawned",
        {
            "source": "spawn",
            "run_id": deps.parent_task_id,
            "total": len(review_prepared),
            "submitted": len(review_prepared),
            "reused": 0,
            "specs": [item.label for item in review_prepared],
            "message": "正在派生最终发布审核子 agent...",
        },
    )
    await incr("sub_agent_final_reviews")
    return review_prepared, await wait_for_prepared_tasks(review_prepared, deps)


async def _submit_final_review(
    review_prepared: list[PreparedTask],
    deps: SpawnAgentDeps,
) -> None:
    if deps.sub_agent_policy.final_review_counts_toward_capacity and hasattr(
        deps.task_queue,
        "submit_many_with_capacity",
    ):
        await deps.task_queue.submit_many_with_capacity(
            CapacitySubmitRequest(
                max_active=deps.sub_agent_policy.max_concurrent,
                specs=[
                    QueueSubmitSpec(
                        task_id=item.task_id,
                        input_data=item.input_data,
                        timeout_seconds=item.timeout_seconds,
                    )
                    for item in review_prepared
                ],
            )
        )
        return
    if deps.sub_agent_policy.final_review_counts_toward_capacity:
        existing = await deps.task_queue.get_children(deps.parent_task_id)
        validate_dispatch_capacity(len(review_prepared), existing, deps.sub_agent_policy)
    for item in review_prepared:
        await deps.task_queue.submit(
            item.task_id,
            item.input_data,
            timeout_seconds=item.timeout_seconds,
        )


def should_run_final_review(
    prepared: list[PreparedTask],
    statuses: list[TaskPayload],
    deps: SpawnAgentDeps,
) -> bool:
    if not deps.sub_agent_policy.enable_final_review or not deps.parent_task_id or len(prepared) < 2:
        return False
    if any(item.input_data.get("template") == FINAL_REVIEW_TEMPLATE for item in prepared):
        return False
    if any(status.status not in {TaskStatus.SUCCEEDED, TaskStatus.FAILED} for status in statuses):
        return False
    return any(status.status == TaskStatus.SUCCEEDED for status in statuses)


def build_final_review_task(
    prepared: list[PreparedTask],
    statuses: list[TaskPayload],
) -> SpawnAgentTask:
    return SpawnAgentTask(
        role=FINAL_REVIEW_ROLE,
        template=FINAL_REVIEW_TEMPLATE,
        input=_review_input(prepared, statuses),
        permission="readonly",
        timeout_seconds=180.0,
        max_iterations=8,
    )


def _review_input(prepared: list[PreparedTask], statuses: list[TaskPayload]) -> str:
    task_labels = "\n".join(f"- {item.task_id}: {item.label}" for item in prepared)
    result = format_result(prepared, statuses)
    return (
        "请作为复杂多 agent 团队任务的最后审核专家，审核以下子任务结果是否足以形成"
        "可发布交付物。\n\n"
        "你的职责：\n"
        "1. 判断是否完整、可信、适合发送飞书文件。\n"
        "2. 发现明显乱掉的 Markdown 排版时做最小修复。\n"
        "3. 不重写内容、不改变结论、不改变章节顺序。\n"
        "4. 若只有预览或缺少完整正文，approved=false。\n"
        "5. 如果结果引用完整文件路径，可用 read_history full/range 读取原文。\n\n"
        "必须只返回 AgentResultV1 JSON object。extra.decision 只能是 send_file 或 block_file。"
        "如需返回修复后的 Markdown，放入 raw_output。\n\n"
        f"子任务列表：\n{task_labels}\n\n"
        f"子任务结果：\n{result.output}"
    )


__all__ = [
    "FINAL_REVIEW_ROLE",
    "FINAL_REVIEW_TEMPLATE",
    "build_final_review_task",
    "run_final_review_if_needed",
    "should_run_final_review",
]
