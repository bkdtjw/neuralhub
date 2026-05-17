from __future__ import annotations

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult
from backend.core.s05_skills.on_demand_loader import OnDemandSkillLoader


def create_load_skill_tool(loader: OnDemandSkillLoader) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="load_skill",
        description=(
            "加载指定 Skill 的完整知识到当前对话。inject 模式：知识注入当前上下文 Zone 2。"
            "loop 模式：开专用执行环境。"
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "skill_id": {"type": "string", "description": "Skill ID，从 query_specs 获取"},
            },
            required=["skill_id"],
        ),
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            skill_id = str(args.get("skill_id", "")).strip()
            if not skill_id:
                return ToolResult(output="skill_id is required", is_error=True)
            return ToolResult(output=loader.load_skill(skill_id).model_dump_json())
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute
