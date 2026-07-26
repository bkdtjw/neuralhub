from __future__ import annotations

from typing import Literal, Protocol

from backend.core.s05_skills.models import SubAgentPolicy
from backend.core.task_queue import TaskPayload, TaskStatus

from .spawn_agent_templates import DEFAULT_INLINE_TEMPLATE, known_inline_templates

PermissionMode = Literal["readonly", "writable", "readwrite"]

ACTIVE_STATUSES = {TaskStatus.PENDING, TaskStatus.RUNNING}
DEFAULT_READONLY_TOOLS = ["Read", "Glob", "Grep", "read_history"]
WRITE_TOOL_NAMES = {
    "Append",
    "Bash",
    "Delete",
    "Edit",
    "MultiEdit",
    "Patch",
    "Write",
    "apply_patch",
    "file_delete",
    "file_edit",
    "file_write",
    "str_replace",
    "str_replace_editor",
}
WRITE_TOOL_NAMES_NORMALIZED = {name.lower() for name in WRITE_TOOL_NAMES}


class SpawnGovernanceError(ValueError):
    pass


class SpawnTaskLike(Protocol):
    spec_id: str
    role: str
    template: str
    tools: list[str]


def validate_allowed_specs(tasks: list[SpawnTaskLike], policy: SubAgentPolicy) -> None:
    """白名单语义：空 = 不限制，配置了条目才收紧。"""
    allowed = {item.strip() for item in policy.allowed_specs if item.strip()}
    configured_templates = {item.strip() for item in policy.allowed_inline_templates if item.strip()}
    allowed_templates = configured_templates or set(known_inline_templates())
    for task in tasks:
        label = _task_label(task)
        if not label:
            raise SpawnGovernanceError("子 agent 任务必须声明 spec_id 或 role")
        if task.spec_id.strip():
            if allowed and label not in allowed:
                raise SpawnGovernanceError(f"子 agent spec 未在白名单中: {label}")
            continue
        if not policy.allow_inline_roles:
            raise SpawnGovernanceError(
                f"当前策略已禁用动态角色（allow_inline_roles=false）: {label}"
            )
        _validate_inline_role(task, policy, allowed_templates)


def _validate_inline_role(
    task: SpawnTaskLike,
    policy: SubAgentPolicy,
    allowed_templates: set[str],
) -> None:
    role = task.role.strip()
    template = task.template.strip() or DEFAULT_INLINE_TEMPLATE
    if template not in allowed_templates:
        raise SpawnGovernanceError(f"动态子 agent template 未被允许: {template}")
    if len(role) > policy.role_name_max_length:
        raise SpawnGovernanceError("动态子 agent role 名称过长")
    _validate_inline_tools(task.tools, policy)


def _validate_inline_tools(tools: list[str], policy: SubAgentPolicy) -> None:
    allowed = {item.strip() for item in policy.allowed_inline_tools if item.strip()}
    if not allowed:
        return
    unknown = [name for name in tools if name.strip() and name.strip() not in allowed]
    if unknown:
        raise SpawnGovernanceError(f"动态子 agent 工具不在允许范围: {', '.join(unknown)}")


def validate_dispatch_capacity(
    to_submit_count: int,
    existing_children: list[TaskPayload],
    policy: SubAgentPolicy,
) -> None:
    active_count = sum(1 for item in existing_children if item.status in ACTIVE_STATUSES)
    if active_count + to_submit_count > policy.max_concurrent:
        raise SpawnGovernanceError(
            "子 agent 并发超过上限: "
            f"active={active_count}, requested={to_submit_count}, "
            f"max_concurrent={policy.max_concurrent}"
        )


def normalize_permission(permission: str) -> PermissionMode:
    value = permission.strip().lower()
    if value in {"", "readonly"}:
        return "readonly"
    if value in {"writable", "readwrite"}:
        return "writable"
    raise SpawnGovernanceError(f"不支持的子 agent permission: {permission}")


def filter_tools_for_permission(
    tools: list[str],
    permission: PermissionMode,
) -> list[str]:
    if permission != "readonly":
        return tools
    source = tools or DEFAULT_READONLY_TOOLS
    return [name for name in source if not is_write_tool_name(name)]


def is_write_tool_name(name: str) -> bool:
    return name.strip().lower() in WRITE_TOOL_NAMES_NORMALIZED


def _task_label(task: SpawnTaskLike) -> str:
    return task.spec_id.strip() or task.role.strip()


__all__ = [
    "DEFAULT_READONLY_TOOLS",
    "SpawnGovernanceError",
    "WRITE_TOOL_NAMES",
    "filter_tools_for_permission",
    "is_write_tool_name",
    "normalize_permission",
    "validate_allowed_specs",
    "validate_dispatch_capacity",
]
