from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin import zhetaoke
from backend.core.s02_tools.builtin.zhetaoke_client import (
    ZHETAOKE_DETAIL_URL,
    ZhetaokeCredentials,
    ZhetaokeDetailRequest,
    ZhetaokeProduct,
    fetch_product_detail,
)


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.url = ""
        self.params: dict[str, str] = {}

    async def get(self, url: str, params: dict[str, str]) -> FakeResponse:
        self.url = url
        self.params = params
        return FakeResponse(self.payload)


def _detail_payload() -> dict[str, Any]:
    return {
        "status": 200,
        "content": [
            {
                "code": "6646",
                "tao_id": "10025768652616",
                "title": "储物箱整理抽屉式收纳柜",
                "tao_title": "抽屉式收纳箱塑料储物箱整理箱",
                "pict_url": "https://img.example/item.jpg",
                "size": "26.90",
                "quanhou_jiage": "16.90",
                "coupon_info": "满80.00元减10元",
                "coupon_info_money": "10",
                "tkrate3": "30.00",
                "tkfee3": "5.07",
                "shop_title": "旗舰店",
                "item_url": "https://item.jd.com/10025768652616.html",
                "haopinglv": "100",
            }
        ],
    }


@pytest.mark.asyncio
async def test_fetch_product_detail_parses_response() -> None:
    fake_client = FakeClient(_detail_payload())

    products = await fetch_product_detail(
        ZhetaokeCredentials(appkey="app-key"),
        ZhetaokeDetailRequest(tao_id="10025768652616"),
        fake_client,  # type: ignore[arg-type]
    )

    assert fake_client.url == ZHETAOKE_DETAIL_URL
    assert fake_client.params["appkey"] == "app-key"
    assert fake_client.params["tao_id"] == "10025768652616"
    assert products[0].tao_id == "10025768652616"
    assert products[0].coupon_price == "16.90"
    assert products[0].coupon_info == "满80.00元减10元"


@pytest.mark.asyncio
async def test_zhetaoke_tool_returns_report(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_mock = AsyncMock(
        return_value=[
            ZhetaokeProduct(
                tao_id="10025768652616",
                title="Apple iPhone",
                price="5999",
                coupon_price="5899",
                coupon_info="满5999减100",
                item_url="https://item.jd.com/10025768652616.html",
            )
        ]
    )
    monkeypatch.setattr(zhetaoke, "fetch_product_detail", fetch_mock)
    _, execute = zhetaoke.create_zhetaoke_product_detail_tool("app-key")

    result = await execute({"tao_id": "10025768652616"})

    assert result.is_error is False
    assert "Apple iPhone" in result.output
    assert "5899" in result.output
    request = fetch_mock.await_args.args[1]
    assert request.tao_id == "10025768652616"


@pytest.mark.asyncio
async def test_zhetaoke_tool_requires_appkey() -> None:
    _, execute = zhetaoke.create_zhetaoke_product_detail_tool("")

    result = await execute({"tao_id": "10025768652616"})

    assert result.is_error is True
    assert "ZHETAOKE_APP_KEY" in result.output


def test_builtin_tools_registers_zhetaoke_detail() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("zhetaoke_product_detail")
