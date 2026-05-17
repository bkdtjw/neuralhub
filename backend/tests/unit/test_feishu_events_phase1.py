from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes import feishu_events as feishu_events_module
from backend.api.routes.feishu_events import FeishuEventDispatcher, router
from backend.config.settings import settings


@pytest.mark.asyncio
async def test_feishu_events_challenge_response() -> None:
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feishu/events",
            json={"type": "url_verification", "challenge": "abc"},
        )
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc"}


@pytest.mark.asyncio
async def test_feishu_events_decrypts_and_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.feishu_encrypt_key = "encrypt-key"
    monkeypatch.setattr(feishu_events_module, "verify_signature", lambda *args: True)
    monkeypatch.setattr(
        feishu_events_module,
        "decrypt_payload",
        lambda encrypt, key: {
            "header": {"event_type": "morning.test"},
            "event": {"value": encrypt, "key": key},
        },
    )

    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        return {"handled": payload["event"]["value"]}

    custom_dispatcher = FeishuEventDispatcher()
    custom_dispatcher.register("morning.test", handler)
    monkeypatch.setattr(feishu_events_module, "dispatcher", custom_dispatcher)

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/feishu/events", json={"encrypt": "cipher"})

    assert response.status_code == 200
    assert response.json() == {"handled": "cipher"}


@pytest.mark.asyncio
async def test_feishu_events_uses_only_real_lark_signature_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def capture_verify(*args: Any) -> bool:
        captured["timestamp"] = str(args[1])
        captured["nonce"] = str(args[2])
        captured["signature"] = str(args[3])
        return True

    monkeypatch.setattr(feishu_events_module, "verify_signature", capture_verify)
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feishu/events",
            json={"header": {"event_type": "morning.test"}},
            headers={
                "X-Lark-Signature-Timestamp": "old-ts",
                "X-Lark-Signature-Signature": "old-sig",
            },
        )

    assert response.status_code == 200
    assert captured == {"timestamp": "", "nonce": "", "signature": ""}
