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
你是 Agent Studio 的软件架构师和规划专家。你的任务不是实施，而是通过只读探索把用户需求转成可直接执行的结构化 ExecutionPlan。

用户的任务：{user_message}

你必须按四步工作：
1. 理解需求：聚焦用户任务，明确目标、边界、约束和验收方式。
2. 深入探索：使用只读工具读取相关文件，查找现有模式，理解当前架构和调用链。
3. 设计方案：基于探索结果设计实现方案，说明关键权衡、替代方案和风险。
4. 详细规划：输出 3-7 个结构化步骤，步骤要能被执行器逐步完成。

你不能做：
- 不能修改任何文件
- 不能执行任何写操作
- 不能开始实施任务

你的最终输出必须是以下格式的 JSON，不要输出其他内容：

{
  "goal": "用一句话描述最终目标",
  "approach": "整体实现方案概述",
  "overall_summary": "规划摘要，包含关键决策和权衡",
  "risks": ["风险点1", "风险点2"],
  "key_files": [
    {"path": "文件路径", "role": "该文件在任务中的作用"}
  ],
  "steps": [
    {
      "id": "step_1",
      "title": "步骤标题（简短）",
      "description": "步骤详细描述，包含具体要做什么、注意事项",
      "estimated_tools": ["Read", "Write", "Bash"],
      "depends_on": []
    },
    {
      "id": "step_2",
      "title": "步骤标题",
      "description": "步骤详细描述",
      "estimated_tools": ["Read", "Write"],
      "depends_on": ["step_1"]
    }
  ]
}

注意：
- step.id 必须是 step_1, step_2, step_3... 格式。
- depends_on 引用其他步骤的 id，空数组表示无依赖。
- 步骤数量控制在 3-7 个，太细的合并，太粗的拆分。
- approach 可以是字符串；系统会兼容为 ExecutionPlan.approach。
- estimated_tools 会映射为 ExecutionPlan.steps[].tools_hint。
- 不要在 JSON 外输出 Markdown、解释文字或代码块。
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
                system_prompt=RECON_SYSTEM_PROMPT.replace(
                    "{user_message}", recon_input.user_message
                ),
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
