from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools.builtin import feishu_client as feishu_module
from backend.core.s02_tools.builtin.feishu_client import FeishuClient


class FakeResponse:
    def json(self) -> dict[str, Any]:
        return {"code": 0, "data": {"image_key": "img_v2_abc"}}


class FakeAsyncClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, timeout: float, trust_env: bool) -> None:
        self.timeout = timeout
        self.trust_env = trust_env

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


@pytest.mark.asyncio
async def test_upload_image_posts_multipart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeAsyncClient.calls = []
    monkeypatch.setattr(feishu_module.httpx, "AsyncClient", FakeAsyncClient)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"png")
    client = FeishuClient("app", "secret")
    client._token = "token"
    client._token_expires = time.time() + 3600

    image_key = await client.upload_image(image_path)

    assert image_key == "img_v2_abc"
    assert FakeAsyncClient.calls[0]["data"] == {"image_type": "message"}
    assert FakeAsyncClient.calls[0]["files"]["image"][0] == "a.png"


@pytest.mark.asyncio
async def test_send_image_uses_image_message_type() -> None:
    client = FeishuClient("app", "secret")
    client.send_message = AsyncMock(return_value={"code": 0})
    result = await client.send_image("chat", "img_v2_abc")
    assert result == {"code": 0}
    args = client.send_message.call_args.args
    kwargs = client.send_message.call_args.kwargs
    assert args[0] == "chat"
    assert json.loads(args[1]) == {"image_key": "img_v2_abc"}
    assert kwargs["msg_type"] == "image"
