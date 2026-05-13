from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.core.s02_tools.builtin.feishu_cards import MorningReport, ReportItem
from backend.storage.run_trace_store import RunTrace, RunTraceStore


async def record_step(
    trace_store: RunTraceStore,
    task_id: str,
    kind: str,
    url: str,
    started: datetime,
    success: bool,
    payload: Any,
) -> None:
    dumped = (
        payload.model_dump(mode="json")
        if isinstance(payload, BaseModel)
        else {"value": str(payload)}
    )
    await trace_store.record(
        RunTrace(
            task_id=task_id,
            kind=kind,
            url=url,
            started_at=started,
            ended_at=datetime.now(),
            success=success,
            error_code="" if success else kind.upper(),
            payload_json=dumped,
        )
    )


async def record_task_trace(
    trace_store: RunTraceStore,
    task_id: str,
    started: datetime,
    success: bool,
    report_path: Path,
    items: list[ReportItem],
) -> None:
    await trace_store.record(
        RunTrace(
            task_id=task_id,
            kind="morning_report",
            started_at=started,
            ended_at=datetime.now(),
            success=success,
            payload_json={"report_path": str(report_path), "items": len(items)},
        )
    )


def render_markdown(report: MorningReport) -> str:
    lines = [f"# Morning Report {report.date}", ""]
    for item in report.items:
        lines.extend([f"## {item.site} - {item.title}", item.url, "", item.summary, ""])
    return "\n".join(lines)


__all__ = ["record_step", "record_task_trace", "render_markdown"]
