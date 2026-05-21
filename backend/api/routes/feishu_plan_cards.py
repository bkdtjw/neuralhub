from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_plan_card(
    *,
    plan_name: str,
    status_text: str,
    steps: Sequence[Any],
    button_value: dict[str, str],
    show_buttons: bool,
    summary: str = "",
    risks: list[str] | None = None,
    report_url: str = "",
    final_template: str = "",
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": _card_markdown(summary, risks, steps)}
    ]
    if show_buttons:
        elements.append({"tag": "action", "actions": _action_buttons(button_value, report_url)})
    template = final_template or "blue"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 {plan_name}"},
            "subtitle": {"tag": "plain_text", "content": status_text},
            "template": template,
        },
        "elements": elements,
    }


def _card_markdown(summary: str, risks: list[str] | None, steps: Sequence[Any]) -> str:
    lines: list[str] = []
    if summary:
        lines.extend(["**方案摘要**", summary[:700], ""])
    risk_items = [item for item in risks or [] if item]
    if risk_items:
        lines.extend(["**风险提示**", f"- {risk_items[0][:120]}", ""])
    lines.append("**步骤**")
    for step in steps:
        status = str(getattr(step, "status", "⬜"))
        title = str(getattr(step, "title", ""))
        detail = str(getattr(step, "detail", ""))
        suffix = f" {detail}" if detail else ""
        lines.append(f"{status} **{title}**{suffix}")
    return "\n".join(lines) or "暂无步骤"


def _action_buttons(value: dict[str, str], report_url: str) -> list[dict[str, Any]]:
    return [
        _callback_button("开始执行", "primary", value, "plan_approve"),
        _url_button("查看详细计划", report_url),
        _callback_button("调整计划", "default", value, "plan_adjust"),
        _callback_button("放弃", "danger", value, "plan_cancel"),
    ]


def _callback_button(
    text: str,
    button_type: str,
    value: dict[str, str],
    action: str,
) -> dict[str, Any]:
    payload = {**value, "action": action, "action_type": action}
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": payload,
    }


def _url_button(text: str, url: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": "default",
        "url": url or "about:blank",
    }


__all__ = ["build_plan_card"]
