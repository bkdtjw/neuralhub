from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin import zhetaoke_search
from backend.core.s02_tools.builtin.zhetaoke_search_client import (
    ZHETAOKE_SEARCH_URL,
    ZhetaokeSearchCredentials,
    ZhetaokeSearchProduct,
    ZhetaokeSearchRequest,
    search_taobao_products,
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


def _search_payload() -> dict[str, Any]:
    return {
        "status": 200,
        "content": [
            {
                "code": "155766354",
                "tao_id": "abc",
                "title": "手机支架",
                "pict_url": "https://img.example/item.jpg",
                "size": "19.90",
                "quanhou_jiage": "9.90",
                "coupon_info": "满10减10",
                "coupon_info_money": "10",
                "tkrate3": "20.00",
                "tkfee3": "1.98",
                "shop_title": "配件店",
                "item_url": "https://uland.taobao.com/item/edetail?id=abc",
                "volume": "1000",
            }
        ],
    }


@pytest.mark.asyncio
async def test_search_taobao_products_parses_response() -> None:
    fake_client = FakeClient(_search_payload())

    products = await search_taobao_products(
        ZhetaokeSearchCredentials(appkey="app-key", sid="sid", pid="pid"),
        ZhetaokeSearchRequest(q="手机支架", page_size=3, sort="price_asc"),
        fake_client,  # type: ignore[arg-type]
    )

    assert fake_client.url == ZHETAOKE_SEARCH_URL
    assert fake_client.params["sid"] == "sid"
    assert fake_client.params["pid"] == "pid"
    assert fake_client.params["q"] == "手机支架"
    assert products[0].title == "手机支架"
    assert products[0].coupon_price == "9.90"


@pytest.mark.asyncio
async def test_zhetaoke_taobao_search_tool_returns_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_mock = AsyncMock(
        return_value=[
            ZhetaokeSearchProduct(
                title="手机支架",
                price="19.90",
                coupon_price="9.90",
                coupon_info="满10减10",
                item_url="https://uland.taobao.com/item/edetail?id=abc",
            )
        ]
    )
    monkeypatch.setattr(zhetaoke_search, "search_taobao_products", search_mock)
    _, execute = zhetaoke_search.create_zhetaoke_taobao_search_tool("app-key", "sid", "pid")

    result = await execute({"q": "手机支架", "page_size": 3})

    assert result.is_error is False
    assert "手机支架" in result.output
    assert "9.90" in result.output
    request = search_mock.await_args.args[1]
    assert request.q == "手机支架"


@pytest.mark.asyncio
async def test_zhetaoke_taobao_search_requires_sid_pid() -> None:
    _, execute = zhetaoke_search.create_zhetaoke_taobao_search_tool("app-key", "", "")

    result = await execute({"q": "手机支架"})

    assert result.is_error is True
    assert "ZHETAOKE_TB_SID" in result.output


def test_builtin_tools_registers_zhetaoke_taobao_search() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("zhetaoke_taobao_search")
