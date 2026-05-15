from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin import jd_union
from backend.core.s02_tools.builtin.jd_union_client import (
    JD_UNION_URL,
    JdUnionCredentials,
    JdUnionGoods,
    JdUnionSearchRequest,
    search_goods,
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


def _goods_payload() -> dict[str, Any]:
    query_result = {
        "code": 200,
        "data": [
            {
                "skuId": "100001",
                "skuName": "Apple iPhone 17",
                "priceInfo": {"price": "5999.00"},
                "commissionInfo": {"commission": "12.34"},
                "shopInfo": {"shopName": "京东自营"},
                "materialUrl": "https://item.jd.com/100001.html",
                "imageInfo": {"imageList": [{"url": "https://img.example/1.jpg"}]},
            }
        ],
    }
    return {
        "jd_union_open_goods_query_response": {
            "code": "0",
            "queryResult": json.dumps(query_result, ensure_ascii=False),
        }
    }


@pytest.mark.asyncio
async def test_search_goods_signs_and_parses_response() -> None:
    fake_client = FakeClient(_goods_payload())

    goods = await search_goods(
        JdUnionCredentials(app_key="app-key", app_secret="secret"),
        JdUnionSearchRequest(keyword="iPhone 17", page_size=1),
        fake_client,  # type: ignore[arg-type]
    )

    assert fake_client.url == JD_UNION_URL
    assert fake_client.params["app_key"] == "app-key"
    assert fake_client.params["sign"].isalnum()
    assert fake_client.params["sign"] == fake_client.params["sign"].upper()
    assert "iPhone 17" in fake_client.params["360buy_param_json"]
    assert goods[0].sku_id == "100001"
    assert goods[0].price == "5999.00"
    assert goods[0].shop_name == "京东自营"


@pytest.mark.asyncio
async def test_jd_union_search_tool_returns_report(monkeypatch: pytest.MonkeyPatch) -> None:
    search_mock = AsyncMock(
        return_value=[
            JdUnionGoods(
                sku_id="100001",
                title="Apple iPhone 17",
                price="5999.00",
                commission="12.34",
                shop_name="京东自营",
                url="https://item.jd.com/100001.html",
            )
        ]
    )
    monkeypatch.setattr(jd_union, "search_goods", search_mock)
    _, execute = jd_union.create_jd_union_search_tool("app-key", "secret")

    result = await execute({"keyword": "iPhone 17", "max_results": 1})

    assert result.is_error is False
    assert "Apple iPhone 17" in result.output
    assert "5999.00" in result.output
    request = search_mock.await_args.args[1]
    assert request.keyword == "iPhone 17"
    assert request.page_size == 1


@pytest.mark.asyncio
async def test_jd_union_search_tool_requires_credentials() -> None:
    _, execute = jd_union.create_jd_union_search_tool("", "")

    result = await execute({"keyword": "iPhone 17"})

    assert result.is_error is True
    assert "JD_UNION_APP_KEY" in result.output


def test_builtin_tools_registers_jd_union_search() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("jd_union_search")
