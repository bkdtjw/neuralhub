from __future__ import annotations

from pathlib import Path

from backend.config.settings import settings as app_settings
from backend.core.s01_agent_loop import (
    DetailedPlanWrite,
    ExecutionPlan,
    PlanKeyFile,
    PlanStep,
    build_plan_report_url,
    save_detailed_plan,
)


def test_save_detailed_plan_writes_session_scoped_markdown(tmp_path) -> None:
    plan = ExecutionPlan(
        goal="升级 Plan recon",
        overall_summary="结构化 recon 输出",
        risks=["确认卡片需要保持按钮兼容"],
        key_files=[PlanKeyFile(path="backend/core/s01_agent_loop/plan_recon.py", role="recon")],
        steps=[
            PlanStep(
                step_id=1,
                title="实现 recon",
                description="让 recon 输出结构化计划。",
                tools_hint=["Read", "Write"],
                depends_on=[],
            )
        ],
    )
    path = save_detailed_plan(
        DetailedPlanWrite(
            base_dir=tmp_path,
            session_id="feishu-chat",
            plan_name="solid-plan",
            plan=plan,
        )
    )
    content = path.read_text(encoding="utf-8")
    assert path.name == "feishu-chat-solid-plan.md"
    assert "## 整体方案摘要" in content
    assert "确认卡片需要保持按钮兼容" in content
    assert "`backend/core/s01_agent_loop/plan_recon.py`" in content
    assert "预估工具: Read, Write" in content


def test_build_plan_report_url_uses_reports_plans_route(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "server_base_url", "http://example.com:8443")
    path = Path("/tmp/计划.md")
    url = build_plan_report_url(path)
    assert url == "http://example.com:8443/reports/plans/%E8%AE%A1%E5%88%92.md"
    assert path.name == "计划.md"
