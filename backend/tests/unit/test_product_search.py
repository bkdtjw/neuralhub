from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import product_search, register_builtin_tools
from backend.core.s02_tools.builtin.zhetaoke_brand_client import ZhetaokeBrandResult
from backend.core.s02_tools.builtin.zhetaoke_search_client import ZhetaokeSearchProduct


@pytest.mark.asyncio
async def test_product_search_merges_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    search_mock = AsyncMock(
        return_value=[
            ZhetaokeSearchProduct(
                tao_id="a",
                title="搜索便宜商品",
                coupon_price="9.90",
                item_url="https://uland.taobao.com/item/edetail?id=a",
            ),
            ZhetaokeSearchProduct(
                tao_id="dup",
                title="重复商品",
                coupon_price="19.90",
                item_url="https://uland.taobao.com/item/edetail?id=dup",
            ),
        ]
    )
    brand_mock = AsyncMock(
        return_value=ZhetaokeBrandResult(
            products=[
                ZhetaokeSearchProduct(
                    tao_id="dup",
                    title="重复商品",
                    coupon_price="19.90",
                    item_url="https://uland.taobao.com/item/edetail?id=dup",
                ),
                ZhetaokeSearchProduct(
                    tao_id="b",
                    title="精选品牌商品",
                    coupon_price="12.90",
                    item_url="https://uland.taobao.com/item/edetail?id=b",
                ),
            ]
        )
    )
    monkeypatch.setattr(product_search, "search_taobao_products", search_mock)
    monkeypatch.setattr(product_search, "fetch_brand_products", brand_mock)
    _, execute = product_search.create_product_search_tool("app-key", "sid", "pid")

    result = await execute({"q": "手机支架", "max_results": 5, "sort_by": "coupon_price"})

    assert result.is_error is False
    assert result.output.count("重复商品") == 1
    assert result.output.index("搜索便宜商品") < result.output.index("精选品牌商品")
    assert "[全网搜索]" in result.output
    assert "[精选品牌]" in result.output


@pytest.mark.asyncio
async def test_product_search_can_skip_brand_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    search_mock = AsyncMock(return_value=[])
    brand_mock = AsyncMock(return_value=ZhetaokeBrandResult(products=[]))
    monkeypatch.setattr(product_search, "search_taobao_products", search_mock)
    monkeypatch.setattr(product_search, "fetch_brand_products", brand_mock)
    _, execute = product_search.create_product_search_tool("app-key", "sid", "pid")

    result = await execute({"q": "手机支架", "include_brand_pool": False})

    assert result.is_error is False
    brand_mock.assert_not_awaited()
    assert "未返回商品数据" in result.output


@pytest.mark.asyncio
async def test_product_search_requires_credentials() -> None:
    _, execute = product_search.create_product_search_tool("app-key", "", "")

    result = await execute({"q": "手机支架"})

    assert result.is_error is True
    assert "ZHETAOKE_TB_SID" in result.output


def test_builtin_tools_registers_product_search() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("product_search")
