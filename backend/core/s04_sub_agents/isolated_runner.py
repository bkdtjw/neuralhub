from __future__ import annotations

import asyncio

from backend.common.errors import AgentError
from backend.common.types import AgentConfig, AgentEventHandler, SubAgentResult
from backend.core.s01_agent_loop import AgentLoop
from backend.core.system_prompt import build_system_prompt

from .permission_policy import build_isolated_registry
from .runtime_models import IsolatedAgentRun, IsolatedAgentRuntime, IsolatedRegistryConfig


def _build_sub_agent_system_prompt(run: IsolatedAgentRun, workspace: str) -> str:
    permission_desc = {
        "readonly": "你只能读取文件和执行只读命令，不能修改、创建或删除文件。",
        "readwrite": "你可以读取和修改文件，也可以执行 shell 命令。",
    }
    description = run.description or f"围绕 {run.task.role} 角色完成分配任务。"
    parts = [
        build_system_prompt(),
        f'你是一个专注于"{run.task.role}"的子 Agent。',
        f"职责：{description}",
        f"权限：{permission_desc[run.task.permission]}",
    ]
    if run.system_prompt:
        parts.append(run.system_prompt)
    parts.extend(
        [
            "规则：",
            "1. 你只能看到当前分配的任务和显式提供的依赖结果。",
            "2. 你不能与其他子 Agent 通信，也看不到主对话历史。",
            "3. 输出要结构化、可复用，便于后续阶段直接消费。",
            "4. 如果无法完成任务，明确说明原因和已完成部分。",
            "5. 回复使用中文，不要使用加粗星号。",
        ]
    )
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _build_task_with_dependencies(run: IsolatedAgentRun) -> str:
    parts = [run.task.task]
    for role_name in run.task.depends_on:
        dependency_output = run.dependency_outputs.get(role_name)
        if dependency_output:
            parts.append(f"[来自 {role_name} 的结果]\n{dependency_output}")
    return "\n\n".join(parts)


def _format_agent_error(role_name: str, exc: AgentError) -> str:
    return f"子 Agent [{role_name}] 执行失败：[{exc.code}] {exc.message}"


async def run_isolated_agent(
    run: IsolatedAgentRun,
    runtime: IsolatedAgentRuntime,
    on_event: AgentEventHandler | None = None,
) -> SubAgentResult:
    try:
        loop = AgentLoop(
            config=AgentConfig(
                model=run.model or runtime.config.default_model,
                system_prompt=_build_sub_agent_system_prompt(run, runtime.config.workspace),
                workspace=runtime.config.workspace,
                max_iterations=run.max_iterations,
                max_consecutive_tool_failures=5,
            ),
            adapter=runtime.adapter,
            tool_registry=build_isolated_registry(
                runtime.parent_registry,
                IsolatedRegistryConfig(
                    permission_level=run.task.permission,
                    allowed_tool_names=run.task.allowed_tools,
                    workspace=runtime.config.workspace,
                ),
            ),
        )
        if on_event is not None:
            loop.on(on_event)
        result = await asyncio.wait_for(
            loop.run(_build_task_with_dependencies(run)),
            timeout=runtime.config.timeout_per_agent,
        )
        return SubAgentResult(role=run.task.role, stage_id=-1, output=result.content.strip())
    except TimeoutError:
        return SubAgentResult(
            role=run.task.role,
            stage_id=-1,
            output=(
                f"子 Agent [{run.task.role}] "
                f"执行超时（{runtime.config.timeout_per_agent:.0f}s）"
            ),
            is_error=True,
        )
    except AgentError as exc:
        return SubAgentResult(
            role=run.task.role,
            stage_id=-1,
            output=_format_agent_error(run.task.role, exc),
            is_error=True,
        )
    except Exception as exc:
        error = AgentError("SUB_AGENT_EXECUTION_ERROR", str(exc))
        return SubAgentResult(
            role=run.task.role,
            stage_id=-1,
            output=_format_agent_error(run.task.role, error),
            is_error=True,
        )


__all__ = ["run_isolated_agent"]
