from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .zhetaoke_brand_client import (
    ZhetaokeBrandCredentials,
    ZhetaokeBrandRequest,
    fetch_brand_products,
)
from .zhetaoke_search_client import (
    ZhetaokeSearchCredentials,
    ZhetaokeSearchProduct,
    ZhetaokeSearchRequest,
    search_taobao_products,
)


class ProductSearchArgs(BaseModel):
    q: str = ""
    max_results: int = Field(default=8, ge=1, le=20)
    sort_by: str = "coupon_price"
    only_coupon: bool = True
    include_brand_pool: bool = True
    min_commission_rate: str = ""
    min_price: str = ""
    max_price: str = ""


def create_product_search_tool(
    appkey: str = "",
    sid: str = "",
    pid: str = "",
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="product_search",
        description=(
            "Search products from multiple verified affiliate data sources and merge results. "
            "Currently uses Zhetaoke Taobao full-network search plus selected-brand pool."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "q": {"type": "string", "description": "商品关键词、店铺名或商品链接"},
                "max_results": {"type": "integer", "description": "返回数量，默认 8，最大 20"},
                "sort_by": {"type": "string", "description": "coupon_price、commission、volume、source"},
                "only_coupon": {"type": "boolean", "description": "是否只看有券商品，默认 true"},
                "include_brand_pool": {"type": "boolean", "description": "是否补充精选品牌池"},
                "min_commission_rate": {"type": "string", "description": "佣金率下限，如 10"},
                "min_price": {"type": "string", "description": "券后价/折扣价下限"},
                "max_price": {"type": "string", "description": "券后价/折扣价上限"},
            },
            required=[],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            params = _parse_args(args)
            credentials = _load_credentials(appkey, sid, pid)
            products = await _collect_products(params, credentials)
            merged = _sort_products(_dedupe_products(products), params.sort_by)[: params.max_results]
            return ToolResult(output=_format_report(params, merged))
        except (ValueError, Exception) as exc:  # noqa: BLE001
            return ToolResult(output=f"商品聚合搜索失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, Any]) -> ProductSearchArgs:
    try:
        return ProductSearchArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise ValueError(f"参数错误：{message}") from exc


def _load_credentials(appkey: str, sid: str, pid: str) -> ZhetaokeSearchCredentials:
    credentials = ZhetaokeSearchCredentials(
        appkey=(appkey or os.environ.get("ZHETAOKE_APP_KEY", "")).strip(),
        sid=(sid or os.environ.get("ZHETAOKE_TB_SID", "")).strip(),
        pid=(pid or os.environ.get("ZHETAOKE_TB_PID", "")).strip(),
    )
    if not credentials.appkey or not credentials.sid or not credentials.pid:
        raise ValueError("请配置 ZHETAOKE_APP_KEY、ZHETAOKE_TB_SID 和 ZHETAOKE_TB_PID")
    return credentials


async def _collect_products(
    params: ProductSearchArgs,
    credentials: ZhetaokeSearchCredentials,
) -> list[tuple[str, ZhetaokeSearchProduct]]:
    products: list[tuple[str, ZhetaokeSearchProduct]] = []
    search_items = await search_taobao_products(
        credentials,
        ZhetaokeSearchRequest(
            q=params.q,
            page_size=params.max_results,
            sort=_to_search_sort(params.sort_by),
            youquan="1" if params.only_coupon else "",
            start_tk_rate=params.min_commission_rate,
            start_price=params.min_price,
            end_price=params.max_price,
        ),
    )
    products.extend(("全网搜索", item) for item in search_items)
    if params.include_brand_pool:
        brand_result = await fetch_brand_products(
            ZhetaokeBrandCredentials(**credentials.model_dump()),
            ZhetaokeBrandRequest(page_size=min(params.max_results, 10), sort="new"),
        )
        products.extend(("精选品牌", item) for item in brand_result.products)
    return products


def _to_search_sort(sort_by: str) -> str:
    mapping = {
        "coupon_price": "price_asc",
        "price": "price_asc",
        "commission": "commission_rate_desc",
        "volume": "sale_num_desc",
        "source": "new",
    }
    return mapping.get(sort_by, "price_asc")


def _dedupe_products(
    products: list[tuple[str, ZhetaokeSearchProduct]],
) -> list[tuple[str, ZhetaokeSearchProduct]]:
    seen: set[str] = set()
    unique: list[tuple[str, ZhetaokeSearchProduct]] = []
    for source, item in products:
        key = item.tao_id or item.item_url or item.title
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append((source, item))
    return unique


def _sort_products(
    products: list[tuple[str, ZhetaokeSearchProduct]],
    sort_by: str,
) -> list[tuple[str, ZhetaokeSearchProduct]]:
    reverse = sort_by in {"commission", "volume"}
    return sorted(products, key=lambda pair: _sort_value(pair[1], sort_by), reverse=reverse)


def _sort_value(item: ZhetaokeSearchProduct, sort_by: str) -> float:
    if sort_by in {"commission", "volume"}:
        value = item.commission_rate if sort_by == "commission" else item.volume
        return _number(value)
    return _number(item.coupon_price or item.price)


def _number(value: str) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or "0")
    except ValueError:
        return 0.0


def _format_report(params: ProductSearchArgs, products: list[tuple[str, ZhetaokeSearchProduct]]) -> str:
    label = params.q or "商品"
    if not products:
        return f'商品聚合搜索: "{label}" 未返回商品数据。'
    lines = [f'商品聚合搜索: "{label}"，返回 {len(products)} 个结果']
    for index, (source, item) in enumerate(products, start=1):
        lines.extend(
            [
                "",
                f"{index}. [{source}] {item.title or item.long_title or '(未命名商品)'}",
                f"   商品ID: {item.tao_id or '未知'} | 价格: {item.price or '未知'}",
                f"   券后价: {item.coupon_price or '未知'} | 优惠券: {item.coupon_info or '无'}",
                f"   佣金率: {item.commission_rate or '未知'} | 返佣: {item.commission or '未知'}",
                f"   店铺: {item.shop_title or '未知'} | 销量: {item.volume or '未知'}",
                f"   链接: {item.item_url or '无'}",
            ]
        )
    return "\n".join(lines)


__all__ = ["ProductSearchArgs", "create_product_search_tool"]
