from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from backend.config.settings import settings as app_settings

from .plan_models import ExecutionPlan, PlanStep

_FILE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_PLAN_PART_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DetailedPlanWrite(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    base_dir: str | Path
    session_id: str
    plan_name: str
    plan: ExecutionPlan


def save_detailed_plan(payload: DetailedPlanWrite) -> Path:
    _validate_file_part(payload.session_id, "session_id")
    _validate_plan_name(payload.plan_name)
    base_dir = Path(payload.base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{payload.session_id}-{payload.plan_name}.md"
    path.write_text(render_detailed_plan(payload.plan_name, payload.plan), encoding="utf-8")
    return path


def build_plan_report_url(report_path: Path) -> str:
    base = app_settings.server_base_url or "http://43.111.233.129:8443"
    encoded_name = quote(report_path.name, safe="")
    return f"{base}/reports/plans/{encoded_name}"


def render_detailed_plan(plan_name: str, plan: ExecutionPlan) -> str:
    lines = [
        f"# {plan_name}",
        "",
        "## 整体方案摘要",
        plan.overall_summary or plan.goal,
        "",
        "## 目标",
        plan.goal,
        "",
        "## 实现方案",
        *_bullets(plan.approach),
        "",
        "## 风险点",
        *_bullets(plan.risks or ["无"]),
        "",
        "## 关键文件与发现",
        *_key_file_lines(plan),
        "",
        "## 分步执行计划",
    ]
    for step in plan.steps:
        lines.extend(_step_lines(step))
    return "\n".join(lines).rstrip() + "\n"


def _key_file_lines(plan: ExecutionPlan) -> list[str]:
    if not plan.key_files:
        return ["- 无"]
    return [f"- `{item.path}`: {item.role or '相关文件'}" for item in plan.key_files]


def _step_lines(step: PlanStep) -> list[str]:
    depends = ", ".join(step.depends_on) if step.depends_on else "无"
    tools = ", ".join(step.tools_hint) if step.tools_hint else "未预估"
    return [
        "",
        f"### Step {step.step_id}: {step.title}",
        "",
        step.description,
        "",
        f"- 预估工具: {tools}",
        f"- 依赖步骤: {depends}",
    ]


def _bullets(values: list[str]) -> list[str]:
    return [f"- {item}" for item in values if item] or ["- 无"]


def _validate_plan_name(name: str) -> None:
    if not _PLAN_PART_RE.fullmatch(name):
        raise ValueError(f"Invalid plan name: {name}")


def _validate_file_part(value: str, field_name: str) -> None:
    if not value or not _FILE_PART_RE.fullmatch(value):
        raise ValueError(f"Invalid {field_name}: {value}")


__all__ = [
    "DetailedPlanWrite",
    "build_plan_report_url",
    "render_detailed_plan",
    "save_detailed_plan",
]
