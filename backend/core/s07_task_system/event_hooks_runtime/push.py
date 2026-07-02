from __future__ import annotations

import json
from typing import Any

import httpx

from backend.core.s02_tools.builtin.feishu_notify import _generate_sign
from backend.core.s07_task_system.event_hooks import (
    EventHook,
    HookVerdict,
    PushFn,
)
from backend.core.s07_task_system.event_hooks_runtime import HookRuntimeError


def make_push_fn(
    *,
    feishu_client: Any,
    chat_id: str | None,
    webhook_url: str = "",
    webhook_secret: str = "",
) -> PushFn:
    async def push(hook: EventHook, verdict: HookVerdict) -> None:
        try:
            card = _build_alert_card(hook, verdict)
            if feishu_client and chat_id:
                payload = await feishu_client.send_message(
                    chat_id=chat_id,
                    content=json.dumps(card, ensure_ascii=False),
                    msg_type="interactive",
                )
                _check_client_payload(payload)
                return
            if webhook_url:
                body = _build_webhook_body(card, webhook_secret)
                async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                    resp = await client.post(webhook_url, json=body)
                _check_webhook_response(resp)
                return
            _logger().warning("event_hook_push_channel_missing", hook_id=hook.id)
        except HookRuntimeError:
            raise
        except Exception as exc:
            raise HookRuntimeError(f"HOOK_RUNTIME_PUSH_ERROR: {exc}") from exc

    return push


def _check_client_payload(payload: Any) -> None:
    # 飞书 client 在 code!=0（机器人被移出群/chat_id 失效/无权限）时不抛错，只返回 payload。
    code = payload.get("code") if isinstance(payload, dict) else None
    if code == 0:
        return
    msg = payload.get("msg", "") if isinstance(payload, dict) else ""
    raise HookRuntimeError(f"HOOK_RUNTIME_PUSH_DELIVERY_FAILED: code={code} msg={msg}")


def _check_webhook_response(resp: Any) -> None:
    # 飞书 webhook 常返回 HTTP 200 + body 里 code/StatusCode!=0（签名错/频控）。
    resp.raise_for_status()
    try:
        body = resp.json()
    except Exception:
        return
    if not isinstance(body, dict):
        return
    code = body.get("code", body.get("StatusCode", 0))
    if code not in (0, None):
        msg = body.get("msg", body.get("StatusMessage", ""))
        raise HookRuntimeError(f"HOOK_RUNTIME_PUSH_DELIVERY_FAILED: code={code} msg={msg}")


def _build_alert_card(hook: EventHook, verdict: HookVerdict) -> dict[str, Any]:
    status = verdict.status
    summary = verdict.summary or "（无摘要）"
    lines = [
        f"**局势**：{summary}",
        f"**转机分**：{verdict.turning_score}/100",
        f"**重要度**：{verdict.materiality}/100；推送要求：重要度 ≥ {hook.materiality}，转机分仅供参考。",
    ]
    entries = _entry_lines(verdict)
    if entries:
        lines.extend(["", "**新增信号**", *entries])
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _template_for_status(status),
            "title": {"tag": "plain_text", "content": f"🔔 {hook.name} · {status}"},
        },
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def _entry_lines(verdict: HookVerdict) -> list[str]:
    return [
        f"- [{entry.source}] {entry.text[:220]}"
        for entry in verdict.new_entries[:3]
    ]


def _template_for_status(status: str) -> str:
    if status == "resolved":
        return "green"
    if status == "escalating":
        return "red"
    if status == "developing":
        return "orange"
    return "blue"


def _build_webhook_body(card: dict[str, Any], webhook_secret: str) -> dict[str, Any]:
    body: dict[str, Any] = {"msg_type": "interactive", "card": card}
    if webhook_secret:
        timestamp, sign = _generate_sign(webhook_secret)
        body["timestamp"] = timestamp
        body["sign"] = sign
    return body


def _logger() -> Any:
    from backend.common.logging import get_logger

    return get_logger(component="event_hooks_runtime_push")


__all__ = ["make_push_fn"]
