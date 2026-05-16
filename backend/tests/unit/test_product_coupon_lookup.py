from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin import product_coupon_lookup_parse as parser
from backend.core.s02_tools.builtin import product_coupon_lookup_sources as sources
from backend.core.s02_tools.builtin.jd_union_client import JdUnionGoods
from backend.core.s02_tools.builtin.product_coupon_lookup import create_product_coupon_lookup_tool
from backend.core.s02_tools.builtin.product_coupon_lookup_models import (
    ExpandedLink,
    ProductCouponLookupConfig,
)
from backend.core.s02_tools.builtin.zhetaoke_client import ZhetaokeProduct
from backend.core.s02_tools.builtin.zhetaoke_search_client import ZhetaokeSearchProduct


@pytest.mark.asyncio
async def test_product_coupon_lookup_parses_taobao_share_and_returns_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        parser,
        "expand_url",
        AsyncMock(
            return_value=ExpandedLink(
                original_url="https://e.tb.cn/h.demo",
                final_url="https://pages-fast.m.taobao.com/wow/share?shareDetailItemId=750795570344",
                body="var url = 'https://item.taobao.com/item.htm?id=750795570344';",
            )
        ),
    )
    monkeypatch.setattr(
        sources,
        "fetch_product_detail",
        AsyncMock(
            return_value=[
                ZhetaokeProduct(
                    tao_id="750795570344",
                    title="Nike AF1",
                    price="590",
                    coupon_price="580",
                    coupon_info="满590减10",
                    shop_title="Nike 店铺",
                    item_url="https://item.taobao.com/item.htm?id=750795570344",
                )
            ]
        ),
    )
    _, execute = create_product_coupon_lookup_tool(
        ProductCouponLookupConfig(zhetaoke_appkey="app", zhetaoke_sid="sid", zhetaoke_pid="pid")
    )

    result = await execute(
        {"text": "【淘宝】https://e.tb.cn/h.demo?tk=abc HU287 「Nike/耐克空军一号af1纯白板鞋」"}
    )

    assert result.is_error is False
    assert "平台: taobao" in result.output
    assert "商品ID/SKU: 750795570344" in result.output
    assert "Nike AF1" in result.output
    assert "满590减10" in result.output


@pytest.mark.asyncio
async def test_product_coupon_lookup_parses_jd_short_link_and_returns_union_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        parser,
        "expand_url",
        AsyncMock(
            return_value=ExpandedLink(
                original_url="https://3.cn/demo",
                final_url="https://item.m.jd.com/product/100250129981.html",
            )
        ),
    )
    monkeypatch.setattr(sources, "fetch_product_detail", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        sources,
        "search_goods",
        AsyncMock(
            return_value=[
                JdUnionGoods(
                    sku_id="100250129981",
                    title="耐克NIKE男子休闲鞋",
                    price="799",
                    shop_name="京东自营",
                    url="https://item.jd.com/100250129981.html",
                )
            ]
        ),
    )
    _, execute = create_product_coupon_lookup_tool(
        ProductCouponLookupConfig(jd_app_key="jd-app", jd_app_secret="jd-secret")
    )

    result = await execute(
        {"text": "【京东】https://3.cn/demo 「耐克NIKE男子休闲鞋AIR FORCE 1」"}
    )

    assert result.is_error is False
    assert "平台: jd" in result.output
    assert "商品ID/SKU: 100250129981" in result.output
    assert "耐克NIKE男子休闲鞋" in result.output
    assert "jd_union_search" in result.output


@pytest.mark.asyncio
async def test_product_coupon_lookup_taobao_falls_back_to_similar_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        parser,
        "expand_url",
        AsyncMock(
            return_value=ExpandedLink(
                original_url="https://e.tb.cn/h.demo",
                final_url="https://item.taobao.com/item.htm?id=750795570344",
            )
        ),
    )
    monkeypatch.setattr(sources, "fetch_product_detail", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        sources,
        "search_taobao_products",
        AsyncMock(
            return_value=[
                ZhetaokeSearchProduct(
                    tao_id="similar-1",
                    title="相似 Nike 板鞋",
                    price="399",
                    coupon_price="359",
                    coupon_info="满399减40",
                    item_url="https://item.taobao.com/item.htm?id=similar-1",
                )
            ]
        ),
    )
    _, execute = create_product_coupon_lookup_tool(
        ProductCouponLookupConfig(zhetaoke_appkey="app", zhetaoke_sid="sid", zhetaoke_pid="pid")
    )

    result = await execute({"text": "【淘宝】https://e.tb.cn/h.demo 「Nike 空军一号板鞋」"})

    assert result.is_error is False
    assert "[zhetaoke_search/similar]" in result.output
    assert "不等同于原链接商品" in result.output


def test_builtin_tools_registers_product_coupon_lookup() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("product_coupon_lookup")


def test_builtin_tools_can_hide_internal_product_tools() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None, include_internal_product_tools=False)

    assert registry.has("product_search")
    assert registry.has("product_coupon_lookup")
    assert not registry.has("jd_union_search")
    assert not registry.has("zhetaoke_product_detail")
    assert not registry.has("zhetaoke_taobao_search")
    assert not registry.has("zhetaoke_brand_products")
