from __future__ import annotations

from typing import Any

from backend.adapters.role_router import RoleRouter
from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .main_agent_loop import run_browser_agent
from .models import BrowserAgentConfig


def create_browse_web_tool(role_router: RoleRouter) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="browse_web",
        description=(
            "Open a browser and complete a multi-step web task autonomously. "
            "Use for finding info on websites, scraping data behind login, "
            "and interacting with web UIs. Returns text result."
        ),
        category="browser",
        parameters=ToolParameterSchema(
            properties={
                "task": {"type": "string", "description": "High-level task in natural language"},
                "domain": {"type": "string", "description": "Optional storage_state domain"},
                "max_steps": {"type": "integer", "description": "Default 15, max 30"},
                "vision_provider_id": {"type": "string", "description": "Override vision provider"},
                "main_agent_provider_id": {
                    "type": "string",
                    "description": "Override main agent provider",
                },
            },
            required=["task"],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            task = str(args.get("task", "")).strip()
            if not task:
                return ToolResult(output="task is required", is_error=True)
            max_steps = min(int(args.get("max_steps", 15) or 15), 30)
            result = await run_browser_agent(
                BrowserAgentConfig(
                    task=task,
                    domain=str(args.get("domain", "") or ""),
                    max_steps=max_steps,
                    vision_subagent_provider_id=str(args.get("vision_provider_id", "") or ""),
                    main_agent_provider_id=str(args.get("main_agent_provider_id", "") or ""),
                ),
                role_router,
            )
            output = result.content if result.success else f"Browse failed: {result.reason}"
            return ToolResult(output=output, is_error=not result.success, diffs=[])
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Browse failed: {exc}", is_error=True)

    return definition, execute


__all__ = ["create_browse_web_tool"]
