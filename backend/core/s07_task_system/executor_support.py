from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from backend.config.settings import settings as app_settings

from .models import ScheduledTask

_BEIJING = ZoneInfo("Asia/Shanghai")


def build_card_meta(
    task: ScheduledTask,
    meta: dict[str, Any],
    report_path: Path,
    end_time: datetime,
) -> dict[str, str]:
    return {
        "task_name": task.name,
        "task_id": task.id,
        "status_text": "执行成功" if meta["status"] == "success" else "执行失败",
        "status_time": end_time.strftime("%Y-%m-%d %H:%M"),
        "started_at": meta["started_at"],
        "finished_at": meta["finished_at"],
        "tool_call_count": str(meta["tool_call_count"]),
        "success_count": str(meta.get("success_count", 0)),
        "trigger_type": "定时任务",
        "execution_id": f"{task.id}-{end_time.strftime('%Y%m%d-%H%M%S')}",
        "report_url": build_report_url(report_path),
    }


def build_report_url(report_path: Path) -> str:
    base = app_settings.server_base_url or "http://43.111.233.129:8443"
    encoded_name = quote(report_path.name, safe="")
    return f"{base}/reports/scheduled_tasks/{encoded_name}"


async def save_report(
    task: ScheduledTask,
    agent_reply: str,
    meta: dict[str, Any],
) -> Path:
    report_dir = Path(os.getcwd()) / "reports" / "scheduled_tasks"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(_BEIJING).strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^\w\-]", "_", task.name)[:50]
    filepath = report_dir / f"{task.id}-{safe_name}-{timestamp}.md"
    execution_id = f"{task.id}-{timestamp}"
    status_text = "执行成功" if meta.get("status") == "success" else "执行失败"
    markdown = (
        f"# {task.name}\n\n"
        f"| 项目 | 值 |\n"
        f"|---|---|\n"
        f"| 任务 ID | {task.id} |\n"
        f"| 执行时间 | {meta.get('started_at', '')} |\n"
        f"| 完成时间 | {meta.get('finished_at', '')} |\n"
        f"| 状态 | {status_text} |\n"
        f"| 耗时 | {meta.get('duration', '')} |\n"
        f"| 工具调用次数 | {meta.get('tool_call_count', '')} |\n"
        f"| 工具成功次数 | {meta.get('success_count', 0)} |\n"
        f"| 触发方式 | 定时任务 |\n"
        f"| 执行 ID | {execution_id} |\n\n"
        f"---\n\n"
        f"## 完整执行结果\n\n{agent_reply}\n"
    )
    await asyncio.to_thread(filepath.write_text, markdown, "utf-8")
    return filepath


def save_markdown(task: ScheduledTask, content: str) -> Path:
    output_dir = task.output.output_dir or os.path.join(os.getcwd(), "task_outputs")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{task.name}_{task.id}.md"
    markdown = f"# {task.name}\n\n{content}"
    try:
        filepath.write_text(markdown, encoding="utf-8")
    except PermissionError:
        timestamp = datetime.now(_BEIJING).strftime("%Y%m%d-%H%M%S")
        filepath = Path(output_dir) / f"{task.name}_{task.id}_{timestamp}.md"
        filepath.write_text(markdown, encoding="utf-8")
    return filepath


__all__ = ["build_card_meta", "build_report_url", "save_markdown", "save_report"]
