"""Signature verification for the main Feishu event & card action routes (G2).

Regression cover for work item G2: ``/api/feishu/event`` and the card action
routes previously read non-existent ``X-Lark-Signature-*`` headers, so signature
verification never ran and the routes were effectively unauthenticated. They now
reuse ``backend.common.feishu_signature`` through
``feishu_signature_support.request_signature_ok`` and read the real Lark headers
(``X-Lark-Request-Timestamp`` / ``X-Lark-Request-Nonce`` / ``X-Lark-Signature``).
"""

from __future__ import annotations

import hashlib
import hmac
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


def _token_sig(body: bytes, timestamp: str, token: str) -> str:
    return hmac.new(f"{timestamp}\n{token}".encode(), body, hashlib.sha256).hexdigest()


def _encrypt_sig(body: bytes, timestamp: str, nonce: str, key: str) -> str:
    return hashlib.sha256(f"{timestamp}{nonce}{key}".encode() + body).hexdigest()


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def _signed_headers(body: bytes, token: str) -> dict[str, str]:
    return {
        "X-Lark-Request-Timestamp": TS,
        "X-Lark-Request-Nonce": NONCE,
        "X-Lark-Signature": _token_sig(body, TS, token),
    }


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

    def test_valid_token_signature_accepted(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = b'{"a":1}'
        assert request_signature_ok(_request(_signed_headers(body, "vtoken")), body) is True

    def test_tampered_signature_rejected(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = b'{"a":1}'
        headers = _signed_headers(body, "vtoken")
        headers["X-Lark-Signature"] = "deadbeef"
        assert request_signature_ok(_request(headers), body) is False

    def test_missing_signature_header_rejected_when_token_set(self) -> None:
        settings.feishu_verification_token = "vtoken"
        assert request_signature_ok(_request({}), b'{"a":1}') is False

    def test_no_secret_allows_unsigned_request(self) -> None:
        # dev default: token & encrypt_key both "" (reset by conftest).
        assert request_signature_ok(_request({}), b'{"a":1}') is True

    def test_encrypt_key_signature_accepted(self) -> None:
        settings.feishu_encrypt_key = "ekey"
        body = b'{"encrypt":"x"}'
        headers = {
            "X-Lark-Request-Timestamp": TS,
            "X-Lark-Request-Nonce": NONCE,
            "X-Lark-Signature": _encrypt_sig(body, TS, NONCE, "ekey"),
        }
        assert request_signature_ok(_request(headers), body) is True


class TestEventRouteSignature:
    """`/api/feishu/event` now actually enforces the signature."""

    async def test_challenge_answered_before_signature(self) -> None:
        # Secret configured, but the callback-URL challenge arrives unsigned.
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"type": "url_verification", "challenge": "c123"}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body)
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "c123"}

    async def test_valid_signature_passes_gate(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"header": {"event_type": "demo.other"}}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body, _signed_headers(body, "vtoken"))
        # Reached business logic (ignored branch), i.e. not rejected at the gate.
        assert resp.json() == {"status": "ignored"}

    async def test_tampered_signature_rejected(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"header": {"event_type": "demo.other"}}).encode()
        headers = _signed_headers(body, "vtoken")
        headers["X-Lark-Signature"] = "bad"
        resp = await _post(_event_app(), "/api/feishu/event", body, headers)
        assert resp.json() == {}

    async def test_missing_signature_rejected_when_token_set(self) -> None:
        # Before G2 this leaked through as {"status": "ignored"} (never verified).
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"header": {"event_type": "demo.other"}}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body)
        assert resp.json() == {}

    async def test_no_secret_allows_unsigned_event(self) -> None:
        body = json.dumps({"header": {"event_type": "demo.other"}}).encode()
        resp = await _post(_event_app(), "/api/feishu/event", body)
        assert resp.json() == {"status": "ignored"}


class TestCardActionRouteSignature:
    """`card_action` / `plan_approval` / `tool_approval` now enforce the signature."""

    async def test_challenge_answered_before_signature(self) -> None:
        settings.feishu_verification_token = "vtoken"
        body = json.dumps({"type": "url_verification", "challenge": "cc"}).encode()
        resp = await _post(_card_app(), "/api/feishu/card_action", body)
        assert resp.json() == {"challenge": "cc"}

    async def test_valid_signature_reaches_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.feishu_verification_token = "vtoken"
        dispatch = AsyncMock(return_value={"toast": {"type": "info", "content": "ok"}})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps({"open_id": "ou_1", "action": {"value": {"action_type": "rerun"}}}).encode()
        resp = await _post(
            _card_app(), "/api/feishu/card_action", body, _signed_headers(body, "vtoken")
        )
        assert resp.json() == {"toast": {"type": "info", "content": "ok"}}
        dispatch.assert_awaited_once()

    async def test_tampered_signature_rejected_before_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.feishu_verification_token = "vtoken"
        dispatch = AsyncMock(return_value={"toast": {}})
        monkeypatch.setattr(card_route.dispatcher, "dispatch", dispatch)
        body = json.dumps({"open_id": "ou_1", "action": {"value": {"action_type": "rerun"}}}).encode()
        headers = _signed_headers(body, "vtoken")
        headers["X-Lark-Signature"] = "bad"
        resp = await _post(_card_app(), "/api/feishu/card_action", body, headers)
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
        headers = _signed_headers(body, "vtoken")
        headers["X-Lark-Signature"] = "bad"
        resp = await _post(_card_app(), "/api/feishu/plan_approval", body, headers)
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
