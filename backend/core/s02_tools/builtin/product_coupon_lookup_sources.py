from __future__ import annotations

from typing import Any

from .jd_union_client import JdUnionCredentials, JdUnionSearchRequest, search_goods
from .product_coupon_lookup_models import LookupContext, LookupItem, ProductCouponLookupConfig
from .zhetaoke_client import ZhetaokeCredentials, ZhetaokeDetailRequest, fetch_product_detail
from .zhetaoke_search_client import (
    ZhetaokeSearchCredentials,
    ZhetaokeSearchRequest,
    search_taobao_products,
)


async def lookup_items(
    context: LookupContext,
    max_results: int,
    config: ProductCouponLookupConfig,
) -> tuple[list[LookupItem], list[str]]:
    if context.platform == "taobao":
        return await lookup_taobao(context, max_results, config)
    if context.platform == "jd":
        return await lookup_jd(context, max_results, config)
    return [], ["无法识别平台，请提供【淘宝】或【京东】前缀，或传入明确商品链接。"]


async def lookup_taobao(
    context: LookupContext,
    max_results: int,
    config: ProductCouponLookupConfig,
) -> tuple[list[LookupItem], list[str]]:
    errors: list[str] = []
    items: list[LookupItem] = []
    creds = ZhetaokeCredentials(
        appkey=config.zhetaoke_appkey,
        sid=config.zhetaoke_sid,
        pid=config.zhetaoke_pid,
    )
    for value in taobao_detail_candidates(context):
        try:
            products = await fetch_product_detail(
                creds, ZhetaokeDetailRequest(tao_id=value, detail_type="0")
            )
            items.extend(from_zhetaoke_detail(product) for product in products)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"淘宝详情({value})：{exc}")
    if items or not context.title:
        return dedupe_items(items), errors
    try:
        products = await search_taobao_products(
            ZhetaokeSearchCredentials(
                appkey=config.zhetaoke_appkey,
                sid=config.zhetaoke_sid,
                pid=config.zhetaoke_pid,
            ),
            ZhetaokeSearchRequest(
                q=context.title,
                page_size=max_results,
                sort="price_asc",
                youquan="1",
                filter_type="2",
            ),
        )
        items.extend(from_zhetaoke_search(product) for product in products)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"淘宝相似搜索：{exc}")
    return dedupe_items(items), errors


async def lookup_jd(
    context: LookupContext,
    max_results: int,
    config: ProductCouponLookupConfig,
) -> tuple[list[LookupItem], list[str]]:
    errors: list[str] = []
    items: list[LookupItem] = []
    if config.zhetaoke_appkey and context.item_id:
        try:
            products = await fetch_product_detail(
                ZhetaokeCredentials(
                    appkey=config.zhetaoke_appkey,
                    sid=config.zhetaoke_sid,
                    pid=config.zhetaoke_pid,
                ),
                ZhetaokeDetailRequest(tao_id=f"https://item.jd.com/{context.item_id}.html"),
            )
            items.extend(from_zhetaoke_detail(product) for product in products)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"折淘客京东详情：{exc}")
    keyword = context.item_id or context.title
    if config.jd_app_key and config.jd_app_secret and keyword:
        try:
            goods = await search_goods(
                JdUnionCredentials(
                    app_key=config.jd_app_key,
                    app_secret=config.jd_app_secret,
                    access_token=config.jd_access_token,
                ),
                JdUnionSearchRequest(keyword=keyword, page_size=max_results),
            )
            items.extend(from_jd_goods(item) for item in goods)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"京东联盟搜索：{exc}")
    return dedupe_items(items), errors


def taobao_detail_candidates(context: LookupContext) -> list[str]:
    values = [context.final_url, context.original_url]
    if context.item_id:
        values.extend(
            [
                f"https://item.taobao.com/item.htm?id={context.item_id}",
                f"https://detail.tmall.com/item.htm?id={context.item_id}",
            ]
        )
    return [value for value in dict.fromkeys(values) if value]


def from_zhetaoke_detail(product: Any) -> LookupItem:
    return LookupItem(
        source="zhetaoke_detail",
        title=product.title or product.long_title,
        item_id=product.tao_id,
        price=product.price,
        coupon_price=product.coupon_price,
        coupon_info=product.coupon_info or "无",
        shop=product.shop_title,
        url=product.item_url,
    )


def from_zhetaoke_search(product: Any) -> LookupItem:
    return LookupItem(
        source="zhetaoke_search",
        match_type="similar",
        title=product.title or product.long_title,
        item_id=product.tao_id,
        price=product.price,
        coupon_price=product.coupon_price,
        coupon_info=product.coupon_info or "无",
        shop=product.shop_title,
        volume=product.volume,
        url=product.item_url,
        note="详情查不到时的相似搜索结果，不等同于原链接商品。",
    )


def from_jd_goods(item: Any) -> LookupItem:
    return LookupItem(
        source="jd_union_search",
        match_type="similar",
        title=item.title,
        item_id=item.sku_id,
        price=item.price,
        coupon_info="京东联盟当前返回未包含明确优惠券字段",
        shop=item.shop_name,
        url=item.url,
        note="京东联盟关键词/SKU 搜索结果，请以商品页实际券为准。",
    )


def dedupe_items(items: list[LookupItem]) -> list[LookupItem]:
    seen: set[str] = set()
    unique: list[LookupItem] = []
    for item in items:
        key = item.item_id or item.url or item.title
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


__all__ = [
    "dedupe_items",
    "from_jd_goods",
    "from_zhetaoke_detail",
    "from_zhetaoke_search",
    "lookup_items",
    "lookup_jd",
    "lookup_taobao",
    "taobao_detail_candidates",
]
