from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import AgentConfig, ToolExecuteFn, ToolResult
from backend.core.s02_tools import ToolRegistry

from .agent_loop import AgentLoop

RECON_TIMEOUT_SECONDS = 180.0
RECON_MAX_ITERATIONS = 15
RECON_TOOL_NAMES = {"Read", "Glob", "Grep", "Bash"}
READONLY_BASH_COMMANDS = {
    "cat",
    "head",
    "tail",
    "wc",
    "ls",
    "find",
    "grep",
    "tree",
    "file",
    "stat",
    "du",
    "echo",
    "pwd",
}
READONLY_BASH_PREFIXES = tuple(f"{name} " for name in sorted(READONLY_BASH_COMMANDS)) + ("pwd",)
_UNSAFE_SHELL_TOKENS = (";", "&&", "||", "|", ">", "<", "`", "$(")

RECON_SYSTEM_PROMPT = """
你是一个代码侦察员。你的任务是快速了解项目结构和相关代码，为后续规划提供依据。

用户的任务：{user_message}

你必须做：
1. 了解项目整体结构（目录布局、关键文件）
2. 阅读与任务直接相关的代码文件
3. 识别关键依赖关系和接口

你不能做：
- 不能修改任何文件
- 不能执行任何写操作
- 不能开始实施任务

最后输出一份简洁的侦察报告，包含：
- 项目结构概览（与任务相关的部分）
- 关键文件和它们的职责
- 已识别的依赖关系和约束
- 对任务的初步判断（难点、风险点）

报告控制在 1000 字以内。
""".strip()


@dataclass(frozen=True)
class ReconInput:
    adapter: LLMAdapter
    source_registry: ToolRegistry
    session_id: str
    user_message: str


async def run_recon(recon_input: ReconInput) -> str:
    try:
        registry = build_readonly_registry(recon_input.source_registry)
        loop = AgentLoop(
            config=AgentConfig(
                model="",
                system_prompt=RECON_SYSTEM_PROMPT.format(user_message=recon_input.user_message),
                session_id=f"{recon_input.session_id}-plan-recon",
                max_iterations=RECON_MAX_ITERATIONS,
            ),
            adapter=recon_input.adapter,
            tool_registry=registry,
        )
        result = await asyncio.wait_for(
            loop.run(recon_input.user_message),
            timeout=RECON_TIMEOUT_SECONDS,
        )
        return result.content
    except TimeoutError:
        return "侦察超时，基于有限信息规划"
    except AgentError as exc:
        return f"侦察失败: {exc.message}，基于用户描述规划"
    except Exception as exc:  # noqa: BLE001
        return f"侦察失败: {exc}，基于用户描述规划"


def build_readonly_registry(source: ToolRegistry) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in source.list_definitions():
        if definition.name not in RECON_TOOL_NAMES:
            continue
        tool = source.get(definition.name)
        if tool is None:
            continue
        executor = make_readonly_bash_executor(tool[1]) if definition.name == "Bash" else tool[1]
        registry.register(definition, executor)
    return registry


def make_readonly_bash_executor(original_executor: ToolExecuteFn) -> ToolExecuteFn:
    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            command = str(args.get("command", ""))
            if not is_readonly_bash(command):
                return ToolResult(output="侦察阶段禁止写操作", is_error=True)
            return await original_executor(args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return execute


def is_readonly_bash(command: str) -> bool:
    normalized = _strip_sudo(command.strip())
    if not normalized:
        return False
    if any(token in normalized for token in _UNSAFE_SHELL_TOKENS):
        return False
    try:
        tokens = shlex.split(normalized)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = tokens[0].rsplit("/", maxsplit=1)[-1]
    return executable in READONLY_BASH_COMMANDS


def _strip_sudo(command: str) -> str:
    while command.startswith("sudo "):
        command = command[5:].strip()
    return command


__all__ = [
    "READONLY_BASH_PREFIXES",
    "RECON_MAX_ITERATIONS",
    "RECON_TIMEOUT_SECONDS",
    "ReconInput",
    "build_readonly_registry",
    "is_readonly_bash",
    "make_readonly_bash_executor",
    "run_recon",
]
