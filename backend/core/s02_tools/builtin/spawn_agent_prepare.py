from __future__ import annotations

from backend.common.types import generate_id

from .spawn_agent_governance import filter_tools_for_permission, normalize_permission
from .spawn_agent_support import PreparedTask, SpawnAgentDeps, SpawnAgentTask
from .spawn_agent_templates import (
    DEFAULT_INLINE_TEMPLATE,
    build_inline_system_prompt,
    resolve_inline_tools,
    resolve_max_iterations,
)


def prepare_tasks(tasks: list[SpawnAgentTask], deps: SpawnAgentDeps) -> list[PreparedTask]:
    prepared: list[PreparedTask] = []
    for index, task in enumerate(tasks, start=1):
        prepared.append(_prepare_one(index, task, deps))
    return prepared


def _prepare_one(index: int, task: SpawnAgentTask, deps: SpawnAgentDeps) -> PreparedTask:
    spec_id = task.spec_id.strip()
    template = task.template.strip()
    if not spec_id:
        template = template or DEFAULT_INLINE_TEMPLATE
    spec = deps.spec_registry.get(spec_id) if spec_id else None
    if spec_id and (spec is None or not spec.enabled):
        raise ValueError(f"未找到可用场景：{spec_id}；如需临时角色请改用 role 字段（inline 模式）")
    timeout_seconds = float(task.timeout_seconds or (spec.timeout_seconds if spec is not None else 120))
    permission = normalize_permission(task.permission)
    source_tools = _source_tools(task, spec_id, template, deps)
    if not spec_id and not source_tools:
        raise ValueError(f"动态子 agent template 没有可用工具: {template}")
    max_iterations = resolve_max_iterations(
        task.max_iterations,
        spec.max_iterations if spec is not None else None,
        template,
        deps.sub_agent_policy,
    )
    return PreparedTask(
        index=index,
        task_id=f"sub-agent-{generate_id()}",
        label=spec_id or task.role.strip() or f"inline-task-{index}",
        timeout_seconds=timeout_seconds,
        dag_id=task.id.strip() or task.role.strip() or spec_id or f"task-{index}",
        depends_on=[item.strip() for item in task.depends_on if item.strip()],
        on_dep_failure=task.on_dep_failure,
        required=task.required,
        input_data={
            "id": task.id.strip(),
            "spec_id": spec_id,
            "role": task.role,
            "template": template,
            "system_prompt": _system_prompt(task, spec_id, template),
            "tools": filter_tools_for_permission(source_tools, permission),
            "input": task.input,
            "permission": permission,
            "no_cache": task.no_cache,
            "required": task.required,
            "depends_on": [item.strip() for item in task.depends_on if item.strip()],
            "on_dep_failure": task.on_dep_failure,
            "max_iterations": max_iterations,
            "max_iterations_cap": deps.sub_agent_policy.max_iterations_cap,
            "model": deps.model,
            "provider": deps.provider,
            "timeout_seconds": timeout_seconds,
            "workspace": deps.workspace,
            "parent_task_id": deps.parent_task_id,
        },
    )


def _source_tools(task: SpawnAgentTask, spec_id: str, template: str, deps: SpawnAgentDeps) -> list[str]:
    if spec_id:
        return task.tools
    return resolve_inline_tools(task.tools, template, deps.sub_agent_policy)


def _system_prompt(task: SpawnAgentTask, spec_id: str, template: str) -> str:
    if spec_id or not template:
        return task.system_prompt
    return build_inline_system_prompt(task.role, template, task.system_prompt)


__all__ = ["prepare_tasks"]
