from __future__ import annotations

import json
from typing import Any

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult
from backend.core.s05_skills.registry import SpecRegistry
from backend.core.s05_skills.models import AgentCategory


def create_query_specs_tool(registry: SpecRegistry) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="query_specs",
        description="查询系统中可用的 agent 场景（spec）列表。可按关键词或分类过滤。",
        category="code-analysis",
        parameters=ToolParameterSchema(
            properties={
                "keyword": {"type": "string", "description": "搜索关键词（可选）"},
                "category": {"type": "string", "description": "按分类过滤（可选）"},
            },
            required=[],
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            keyword = str(args.get("keyword", "")).strip()
            category = str(args.get("category", "")).strip()
            items = registry.search(keyword) if keyword else registry.list_all()
            if category:
                try:
                    resolved = AgentCategory(category)
                except ValueError:
                    return ToolResult(output=f"Invalid category: {category}", is_error=True)
                items = [spec for spec in items if spec.category == resolved]
            payload = [
                {
                    "id": spec.id,
                    "title": spec.title,
                    "category": spec.category.value,
                    "description": " ".join(spec.description.split())[:100],
                }
                for spec in items
            ]
            return ToolResult(output=json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute


__all__ = ["create_query_specs_tool"]
