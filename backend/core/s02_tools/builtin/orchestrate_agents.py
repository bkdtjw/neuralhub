from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentEventHandler,
    SimplePlan,
    ToolDefinition,
    ToolExecuteFn,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents import (
    OrchestrationError,
    Orchestrator,
    OrchestratorConfig,
    SubAgentProgressEmitter,
)


def _format_validation_error(exc: ValidationError) -> str:
    details = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in details.get("loc", []))
    message = details.get("msg", str(exc))
    return f"{loc}: {message}" if loc else str(message)


def create_orchestrate_agents_tool(
    adapter: LLMAdapter,
    parent_registry: ToolRegistry,
    config: OrchestratorConfig,
    event_handler: AgentEventHandler | None = None,
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="orchestrate_agents",
        description="执行简化的多子 Agent 协作任务列表，并自动推导并行阶段。",
        category="code-analysis",
        parameters=ToolParameterSchema(
            properties={
                "tasks": {
                    "type": "array",
                    "description": "任务列表。每个任务包含 role、task，可选 permission、allowed_tools、depends_on。",
                    "items": {
                        "type": "object",
                        "required": ["role", "task"],
                        "properties": {
                            "role": {"type": "string"},
                            "task": {"type": "string"},
                            "permission": {"type": "string", "enum": ["readonly", "readwrite"]},
                            "allowed_tools": {"type": "array", "items": {"type": "string"}},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                }
            },
            required=["tasks"],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            plan = SimplePlan.model_validate(args)
            orchestrator = Orchestrator(
                adapter=adapter,
                parent_registry=parent_registry,
                config=config,
                progress=SubAgentProgressEmitter(event_handler, "orchestrate"),
            )
            return await orchestrator.execute(plan)
        except ValidationError as exc:
            return ToolResult(output=f"编排计划格式错误: {_format_validation_error(exc)}", is_error=True)
        except OrchestrationError as exc:
            return ToolResult(output=f"编排执行失败: {exc.message}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"编排执行异常: {exc}", is_error=True)

    return definition, execute


__all__ = ["create_orchestrate_agents_tool"]
