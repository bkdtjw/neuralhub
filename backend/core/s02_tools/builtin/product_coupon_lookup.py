from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .product_coupon_lookup_models import (
    LookupContext,
    LookupItem,
    ProductCouponLookupArgs,
    ProductCouponLookupConfig,
)
from .product_coupon_lookup_parse import build_lookup_context
from .product_coupon_lookup_sources import lookup_items


def create_product_coupon_lookup_tool(
    config: ProductCouponLookupConfig | None = None,
) -> tuple[ToolDefinition, ToolExecuteFn]:
    resolved = config or ProductCouponLookupConfig()
    definition = ToolDefinition(
        name="product_coupon_lookup",
        description=(
            "Lookup coupon and affiliate data for a concrete product from a shared "
            "Taobao/JD link, item id, or copy text. Prefer this over browser "
            "automation for product coupon checks."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "text": {"type": "string", "description": "完整分享文案，如【淘宝】短链「标题」"},
                "url": {"type": "string", "description": "淘宝/京东商品链接或短链"},
                "platform": {"type": "string", "description": "auto、taobao、jd，默认 auto"},
                "title": {"type": "string", "description": "可选商品标题，用于相似搜索兜底"},
                "item_id": {"type": "string", "description": "可选淘宝 item_id 或京东 SKU"},
                "max_results": {"type": "integer", "description": "相似搜索最多返回数，默认 5"},
            },
            required=[],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = ProductCouponLookupArgs.model_validate(args)
            context = await build_lookup_context(parsed)
            items, errors = await lookup_items(context, parsed.max_results, resolved)
            return ToolResult(output=format_lookup_report(context, items, errors))
        except (ValueError, ValidationError) as exc:
            return ToolResult(output=f"商品查券参数错误：{exc}", is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"商品查券失败：{exc}", is_error=True)

    return definition, execute


def format_lookup_report(
    context: LookupContext,
    items: list[LookupItem],
    errors: list[str],
) -> str:
    lines = [
        "商品查券结果",
        f"平台: {context.platform}",
        f"商品ID/SKU: {context.item_id or '未识别'}",
        f"标题: {context.title or '未识别'}",
        f"解析链接: {context.final_url or context.original_url or '无'}",
    ]
    if not items:
        lines.extend(["", "结论: 当前已配置数据源未查到可用优惠券或商品数据。"])
    for index, item in enumerate(items, start=1):
        lines.extend(_item_lines(index, item))
    if errors:
        lines.extend(["", "数据源备注:"])
        lines.extend(f"- {error}" for error in errors[:5])
    return "\n".join(lines)


def _item_lines(index: int, item: LookupItem) -> list[str]:
    lines = [
        "",
        f"{index}. [{item.source}/{item.match_type}] {item.title or '(未命名商品)'}",
        f"   ID: {item.item_id or '未知'} | 价格: {item.price or '未知'}",
        f"   券后价: {item.coupon_price or '未知'} | 优惠券: {item.coupon_info or '无'}",
        f"   店铺: {item.shop or '未知'} | 销量: {item.volume or '未知'}",
        f"   链接: {item.url or '无'}",
    ]
    if item.note:
        lines.append(f"   说明: {item.note}")
    return lines


__all__ = [
    "ProductCouponLookupArgs",
    "ProductCouponLookupConfig",
    "create_product_coupon_lookup_tool",
    "format_lookup_report",
]
