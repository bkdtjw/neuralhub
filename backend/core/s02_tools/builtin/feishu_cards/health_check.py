from __future__ import annotations

from typing import Any

from .models import ButtonSpec, CardAction, button, card


def build_health_check_card(probe_results: list[dict[str, Any]]) -> dict:
    lines = [_format_probe(item) for item in probe_results] or ["No probe results."]
    elements: list[dict] = [{"tag": "markdown", "content": "\n".join(lines)}]
    if any(not bool(item.get("ok", True)) for item in probe_results):
        elements.append(
            {
                "tag": "action",
                "actions": [
                    button(
                        ButtonSpec(
                            text="Start relogin",
                            button_type="primary",
                            action=CardAction(action_type="relogin_start"),
                        )
                    )
                ],
            }
        )
    return card("Morning Report Health Check", elements, template="blue")


def _format_probe(item: dict[str, Any]) -> str:
    site = str(item.get("site") or item.get("domain") or "unknown")
    ok = bool(item.get("ok", True))
    status = "OK" if ok else "Needs attention"
    detail = str(item.get("detail") or "")
    return f"- {site}: {status}{f' - {detail}' if detail else ''}"


__all__ = ["build_health_check_card"]
