from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class StepState:
    step_id: int
    title: str
    status: str = "⬜"
    detail: str = ""


def build_frame_lines(plan_name: str, steps: list[StepState], status_label: str = "") -> list[str]:
    title = f"Plan: {plan_name or '-'}"
    if status_label:
        title = f"{title} [{status_label}]"
    step_lines = [
        f"{step.step_id}. {step.status} {step.title}{(' ' + step.detail) if step.detail else ''}"
        for step in steps
    ]
    cols = shutil.get_terminal_size((80, 24)).columns
    inner_width = max(40, len(title) + 3, *(len(line) + 2 for line in step_lines))
    inner_width = min(inner_width, max(cols - 2, 20))
    top = f"┌─ {_clip(title, inner_width - 3)} "
    lines = [top + "─" * max(0, inner_width - len(top) + 1) + "┐"]
    for step_line in step_lines:
        content = _clip(f" {step_line}", inner_width)
        lines.append(f"│{content}{' ' * max(0, inner_width - len(content))}│")
    lines.append(f"└{'─' * inner_width}┘")
    return lines


def status_icon(status: str) -> str:
    if status == "done":
        return "✅"
    if status == "failed":
        return "❌"
    if status == "running":
        return "⏳"
    return "⬜"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


__all__ = ["StepState", "build_frame_lines", "status_icon"]
