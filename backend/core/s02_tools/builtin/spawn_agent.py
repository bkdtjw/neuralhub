from __future__ import annotations

import asyncio
import json
import re

from backend.common.logging import get_logger
from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult
from backend.core.s02_tools.builtin.spawn_agent_dag import run_prepared_tasks
from backend.core.s02_tools.builtin.spawn_agent_reuse import with_reuse_notice

from .spawn_agent_support import (
    SpawnAgentArgs,
    SpawnAgentDeps,
    format_result,
)
from .spawn_agent_governance import validate_allowed_specs
from .spawn_agent_final_review import run_final_review_if_needed
from .spawn_agent_prepare import prepare_tasks

logger = get_logger(component="spawn_agent")


def _normalize_args(args: dict[str, object]) -> dict[str, object]:
    raw = args.get("raw")
    if "tasks" in args or not isinstance(raw, str) or not raw.strip():
        return args
    for candidate in (raw.strip(), _find_json_block(raw), _find_json_object(raw)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return {str(key): value for key, value in parsed.items()}
    return args


def _find_json_block(raw: str) -> str:
    matched = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    return matched.group(1) if matched else ""


def _find_json_object(raw: str) -> str:
    matched = re.search(r"(\{[\s\S]*\})", raw)
    return matched.group(1) if matched else ""


def create_spawn_agent_tool(deps: SpawnAgentDeps) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="spawn_agent",
        description="派生子 agent 并行执行任务。传入任务数组，所有任务并行执行，等待全部完成后返回结果。",
        category="code-analysis",
        parameters=ToolParameterSchema(
            properties={
                "tasks": {
                    "type": "array",
                    "description": "任务列表，每个任务并行执行",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "依赖编排时的唯一任务 ID，可被 depends_on 引用"},
                            "spec_id": {"type": "string", "description": "已注册的 skill spec ID。和 inline 定义二选一。"},
                            "role": {"type": "string", "description": "自由角色名（inline 模式），如 报告审阅员、竞品分析师，无需预先注册"},
                            "template": {"type": "string", "description": "inline 基础模板（可选，默认 generalist 只读通用型）。可选：generalist/research-specialist/code-reader/code-reviewer/test-strategist/implementer/verifier/synthesis-specialist/product-pm"},
                            "system_prompt": {"type": "string", "description": "角色的补充约束，附加在模板提示词之后"},
                            "tools": {"type": "array", "items": {"type": "string"}, "description": "工具列表（可选）。不传用模板默认；显式传入即为准，readonly 权限下写类工具仍会被剔除"},
                            "input": {"type": "string", "description": "子 agent 的输入文本（必填）"},
                            "permission": {"type": "string", "description": "权限范围：readonly 或 writable，默认 readonly"},
                            "no_cache": {"type": "boolean", "description": "是否跳过同会话历史结果复用，默认 false"},
                            "required": {"type": "boolean", "description": "关键子任务，失败时 spawn_agent 返回 is_error=true"},
                            "depends_on": {"type": "array", "items": {"type": "string"}, "description": "依赖的任务 ID 列表"},
                            "on_dep_failure": {"type": "string", "description": "依赖失败策略：block 或 proceed"},
                            "timeout_seconds": {"type": "number", "description": "超时秒数（可选，默认用 spec 配置或 120）"},
                            "max_iterations": {"type": "integer", "description": "本子任务迭代预算，最终不会超过平台 cap"},
                        },
                        "required": ["input"],
                    },
                }
            },
            required=["tasks"],
        ),
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            payload = SpawnAgentArgs.model_validate(_normalize_args(args))
            if not payload.tasks:
                return ToolResult(output="tasks 不能为空", is_error=True)
            validate_allowed_specs(payload.tasks, deps.sub_agent_policy)
            prepared = prepare_tasks(payload.tasks, deps)
            run = await run_prepared_tasks(prepared, deps)
            review_prepared, review_statuses = await run_final_review_if_needed(
                run.prepared,
                run.statuses,
                deps,
            )
            result = format_result(
                [*run.prepared, *review_prepared],
                [*run.statuses, *review_statuses],
            )
            return with_reuse_notice(result, run.reused_statuses)
        except asyncio.TimeoutError:
            return ToolResult(output="等待子 agent 结果超时", is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute


__all__ = ["create_spawn_agent_tool"]
