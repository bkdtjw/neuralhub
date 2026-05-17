from __future__ import annotations

from backend.common.types import ToolResult
from backend.core.s02_tools import ToolRegistry

from .plan_models import PlanStep


async def execute_script_step(step: PlanStep, registry: ToolRegistry) -> ToolResult:
    tool_name = step.tool_name or (step.tools_hint[0] if step.tools_hint else "")
    if not tool_name:
        return ToolResult(output="script_step requires tool_name or tools_hint[0]", is_error=True)
    tool = registry.get(tool_name)
    if tool is None:
        return ToolResult(output=f"Tool not found for script_step: {tool_name}", is_error=True)
    _, executor = tool
    try:
        result = await executor(step.tool_arguments)
        return result.model_copy(update={"tool_call_id": tool_name})
    except Exception as exc:  # noqa: BLE001
        return ToolResult(tool_call_id=tool_name, output=str(exc), is_error=True)


__all__ = ["execute_script_step"]
