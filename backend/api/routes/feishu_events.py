from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.common.errors import AgentError
from backend.common.feishu_signature import decrypt_payload, verify_signature
from backend.common.logging import get_logger
from backend.config.settings import settings

logger = get_logger(component="feishu_events_route")

router = APIRouter(tags=["feishu-events"])
EventHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class FeishuEventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, EventHandler] = {}

    def register(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type] = handler

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            event_type = _event_type(payload)
            handler = self._handlers.get(event_type, _stub_handler)
            result = await handler(payload)
            return result or {"status": "ok", "event_type": event_type}
        except Exception as exc:  # noqa: BLE001
            logger.error("feishu_event_dispatch_failed", error=str(exc))
            raise AgentError("FEISHU_EVENT_DISPATCH_ERROR", str(exc)) from exc


dispatcher = FeishuEventDispatcher()


def register_handler(event_type: str, handler: EventHandler) -> None:
    dispatcher.register(event_type, handler)


@router.post("/feishu/events")
async def feishu_events(request: Request) -> dict[str, Any]:
    try:
        body = await request.body()
        payload = _decode_json(body)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        if not _signature_ok(request, body):
            raise HTTPException(status_code=401, detail="signature mismatch")
        payload = _decrypt_if_needed(payload)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        return await dispatcher.dispatch(payload)
    except HTTPException:
        raise
    except AgentError as exc:
        logger.error("feishu_events_failed", code=exc.code, error=exc.message)
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("feishu_events_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="invalid feishu event") from exc


async def _stub_handler(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"status": "stub", "event_type": _event_type(payload)}
    except Exception as exc:  # noqa: BLE001
        logger.error("feishu_event_stub_failed", error=str(exc))
        raise AgentError("FEISHU_EVENT_STUB_ERROR", str(exc)) from exc


def _decode_json(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise AgentError("FEISHU_EVENT_INVALID_JSON", "payload must be a JSON object")
        return data
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("FEISHU_EVENT_JSON_ERROR", str(exc)) from exc


def _signature_ok(request: Request, body: bytes) -> bool:
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    return verify_signature(
        body,
        timestamp,
        nonce,
        signature,
        _feishu_verification_token(),
        _feishu_encrypt_key(),
    )


def _decrypt_if_needed(payload: dict[str, Any]) -> dict[str, Any]:
    encrypt = payload.get("encrypt")
    if not isinstance(encrypt, str) or not encrypt:
        return payload
    return decrypt_payload(encrypt, _feishu_encrypt_key())


def _feishu_verification_token() -> str:
    return str(getattr(settings, "feishu_verification_token", "") or "")


def _feishu_encrypt_key() -> str:
    return str(getattr(settings, "feishu_encrypt_key", "") or "")


def _event_type(payload: dict[str, Any]) -> str:
    header = payload.get("header", {})
    if isinstance(header, dict) and header.get("event_type"):
        return str(header["event_type"])
    event = payload.get("event", {})
    if isinstance(event, dict) and event.get("type"):
        return str(event["type"])
    return str(payload.get("type", "unknown"))


__all__ = ["FeishuEventDispatcher", "dispatcher", "register_handler", "router"]
