"""Signature verification for the main Feishu event & card action routes.

按飞书官方协议覆盖两种模式：
- 明文模式（只配 Verification Token）：回调不带 ``X-Lark-Signature`` 头，
  校验方式是比对 body 内 token 字段（v2 在 header.token，v1/卡片在顶层）。
  回归背景：批次 G 曾要求明文回调也必须带签名头，导致生产上配了
  verification_token 后所有入站消息被 ``feishu_signature_invalid`` 拒绝。
- 加密模式（配 Encrypt Key）：校验 sha256(timestamp+nonce+encrypt_key+body)。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.requests import Request

from backend.api.routes import feishu as feishu_route
from backend.api.routes import feishu_card_action as card_route
from backend.api.routes.feishu_signature_support import request_signature_ok
from backend.config.settings import settings

TS = "1700000000"
NONCE = "nonce-abc"


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # Pure in-memory route tests: override conftest DB bind, skip PostgresContainer.
    # (Feishu settings are reset to "" per-test by conftest.reset_feishu_settings.)
    yield


def _encrypt_sig(body: bytes, timestamp: str, nonce: str, key: str) -> str:
    return hashlib.sha256(f"{timestamp}{nonce}{key}".encode() + body).hexdigest()


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def _enc_headers(body: bytes, key: str) -> dict[str, str]:
    return {
        "X-Lark-Request-Timestamp": TS,
        "X-Lark-Request-Nonce": NONCE,
        "X-Lark-Signature": _encrypt_sig(body, TS, NONCE, key),
    }


def _v2_event(token: str, event_type: str = "demo.other") -> bytes:
    return json.dumps(
        {"schema": "2.0", "header": {"event_type": event_type, "token": token}, "event": {}}
    ).encode()


async def _post(
    app: FastAPI, path: str, body: bytes, headers: dict[str, str] | None = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, content=body, headers=headers or {})


def _event_app() -> FastAPI:
    app = FastAPI()
    app.include_router(feishu_route.router)
    return app


def _card_app() -> FastAPI:
    app = FastAPI()
    app.include_router(card_route.router)
    return app


class TestRequestSignatureOk:
    """Direct unit cover of the extracted verification helper."""

    def test_plaintext_v2_header_token_accepted(self) -> None:
        settings.feishu_verification_token = "vtoken"
        assert request_signature_ok(_request({}), _v2_event("vtoken")) is True

    def test_plaintext_top_level_token_accepted(self) -> None:
        # v1 事件 / 老版卡片回调把 token 放在顶层。
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"token": "vtoken", "action": {}}).encode()
        assert request_signature_ok(_request({}), body) is True

    def test_plaintext_wrong_token_rejected(self) -> None:
        settings.feishu_verification_token = "vtoken"
        assert request_signature_ok(_request({}), _v2_event("intruder")) is False

    def test_plaintext_missing_token_field_rejected(self) -> None:
        settings.feishu_verification_token = "vtoken"
        assert request_signature_ok(_request({}), b'{"a":1}') is False

    def test_no_secret_allows_unsigned_request(self) -> None:
        # dev default: token & encrypt_key both "" (reset by conftest).
        assert request_signature_ok(_request({}), b'{"a":1}') is True

    def test_encrypt_key_signature_accepted(self) -> None:
        settings.feishu_encrypt_key = "ekey"
        body = b'{"encrypt":"x"}'
        assert request_signature_ok(_request(_enc_headers(body, "ekey")), body) is True

    def test_encrypt_key_tampered_signature_rejected(self) -> None:
        settings.feishu_encrypt_key = "ekey"
        body = b'{"encrypt":"x"}'
        headers = _enc_headers(body, "ekey")
        headers["X-Lark-Signature"] = "deadbeef"
        assert request_signature_ok(_request(headers), body) is False

    def test_encrypt_key_missing_signature_header_rejected(self) -> None:
        # 加密模式下飞书必带签名头，无头视为伪造。
        settings.feishu_encrypt_key = "ekey"
        assert request_signature_ok(_request({}), b'{"encrypt":"x"}') is False

    def test_token_only_with_signature_header_judged_by_token(self) -> None:
        # 真机抓包实证：明文模式飞书也发签名头（encrypt_key 按空串计算，无鉴权价值）。
        # 只配 token 时须忽略签名头、按 body token 判——正确 token 放行，错误拒绝。
        settings.feishu_verification_token = "vtoken"
        good = _v2_event("vtoken")
        assert request_signature_ok(_request(_enc_headers(good, "")), good) is True
        bad = _v2_event("intruder")
        assert request_signature_ok(_request(_enc_headers(bad, "")), bad) is False


class TestEventRouteSignature:
    """`/api/feishu/event` enforces verification per Feishu's real protocol."""

    async def test_challenge_answered_before_signature(self) -> None:
        # Secret configured, but the callback-URL challenge arrives unsigned.
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"type": "url_verification", "challenge": "c123"}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body)
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "c123"}

    async def test_plaintext_event_with_valid_token_passes_gate(self) -> None:
        settings.feishu_verification_token = "vtoken"
        resp = await _post(_event_app(), "/api/feishu/event", _v2_event("vtoken"))
        # Reached business logic (ignored branch), i.e. not rejected at the gate.
        assert resp.json() == {"status": "ignored"}

    async def test_plaintext_event_with_wrong_token_rejected(self) -> None:
        settings.feishu_verification_token = "vtoken"
        resp = await _post(_event_app(), "/api/feishu/event", _v2_event("intruder"))
        assert resp.json() == {}

    async def test_no_secret_allows_unsigned_event(self) -> None:
        body = json.dumps({"header": {"event_type": "demo.other"}}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body)
        assert resp.json() == {"status": "ignored"}


class TestCardActionRouteSignature:
    """`card_action` / `plan_approval` / `tool_approval` share the same gate."""

    async def test_challenge_answered_before_signature(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"type": "url_verification", "challenge": "cc"}).encode()
        resp = await _post(_card_app(), "/api/feishu/card_action", body)
        assert resp.json() == {"challenge": "cc"}

    async def test_plaintext_card_action_reaches_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.feishu_verification_token = "vtoken"
        dispatch = AsyncMock(return_value={"toast": {"type": "info", "content": "ok"}})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps(
            {"token": "vtoken", "open_id": "ou_1", "action": {"value": {"action_type": "rerun"}}}
        ).encode()
        resp = await _post(_card_app(), "/api/feishu/card_action", body)
        assert resp.json() == {"toast": {"type": "info", "content": "ok"}}
        dispatch.assert_awaited_once()

    async def test_wrong_token_rejected_before_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.feishu_verification_token = "vtoken"
        dispatch = AsyncMock(return_value={"toast": {}})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps(
            {"token": "bad", "open_id": "ou_1", "action": {"value": {"action_type": "rerun"}}}
        ).encode()
        resp = await _post(_card_app(), "/api/feishu/card_action", body)
        assert resp.json() == {}
        dispatch.assert_not_awaited()

    async def test_plan_approval_route_shares_signature_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.feishu_verification_token = "vtoken"
        dispatch = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps(
            {"open_id": "ou_9", "action": {"value": {"action_type": "plan_approve"}}}
        ).encode()
        resp = await _post(_card_app(), "/api/feishu/plan_approval", body)
        assert resp.json() == {}
        dispatch.assert_not_awaited()

    async def test_no_secret_allows_unsigned_card_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatch = AsyncMock(return_value={"ok": 1})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps({"open_id": "ou_1", "action": {"value": {"action_type": "rerun"}}}).encode()
        resp = await _post(_card_app(), "/api/feishu/card_action", body)
        assert resp.json() == {"ok": 1}
        dispatch.assert_awaited_once()
