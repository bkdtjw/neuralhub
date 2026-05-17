from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin import zhetaoke_brand
from backend.core.s02_tools.builtin.zhetaoke_brand_client import (
    ZHETAOKE_BRAND_URL,
    ZhetaokeBrandCredentials,
    ZhetaokeBrandRequest,
    ZhetaokeBrandResult,
    fetch_brand_products,
)
from backend.core.s02_tools.builtin.zhetaoke_search_client import ZhetaokeSearchProduct


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


def _brand_payload() -> dict[str, Any]:
    return {
        "status": 200,
        "total_count": 20,
        "content": [
            {
                "code": "155766354",
                "tao_id": "abc",
                "title": "品牌美背",
                "size": "39.90",
                "quanhou_jiage": "29.90",
                "coupon_info": "满30减10",
                "tkrate3": "15.00",
                "tkfee3": "4.48",
                "shop_title": "品牌店",
                "item_url": "https://uland.taobao.com/item/edetail?id=abc",
            }
        ],
    }


@pytest.mark.asyncio
async def test_fetch_brand_products_parses_response() -> None:
    fake_client = FakeClient(_brand_payload())

    result = await fetch_brand_products(
        ZhetaokeBrandCredentials(appkey="app-key", sid="sid", pid="pid"),
        ZhetaokeBrandRequest(pinpai_name="美的", include_total_count=True),
        fake_client,  # type: ignore[arg-type]
    )

    assert fake_client.url == ZHETAOKE_BRAND_URL
    assert fake_client.params["pinpai"] == "1"
    assert fake_client.params["pinpai_name"] == "美的"
    assert fake_client.params["total_count"] == "1"
    assert result.total_count == 20
    assert result.products[0].title == "品牌美背"


@pytest.mark.asyncio
async def test_zhetaoke_brand_tool_returns_report(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_mock = AsyncMock(
        return_value=ZhetaokeBrandResult(
            total_count=20,
            products=[
                ZhetaokeSearchProduct(
                    title="品牌美背",
                    price="39.90",
                    coupon_price="29.90",
                    item_url="https://uland.taobao.com/item/edetail?id=abc",
                )
            ],
        )
    )
    monkeypatch.setattr(zhetaoke_brand, "fetch_brand_products", fetch_mock)
    _, execute = zhetaoke_brand.create_zhetaoke_brand_products_tool("app-key", "sid", "pid")

    result = await execute({"pinpai_name": "美的", "include_total_count": True})

    assert result.is_error is False
    assert "品牌美背" in result.output
    assert "总数 20" in result.output
    request = fetch_mock.await_args.args[1]
    assert request.pinpai_name == "美的"


def test_builtin_tools_registers_zhetaoke_brand_products() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("zhetaoke_brand_products")
