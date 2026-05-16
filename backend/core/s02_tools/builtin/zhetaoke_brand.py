from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .zhetaoke_brand_client import (
    ZhetaokeBrandCredentials,
    ZhetaokeBrandError,
    ZhetaokeBrandRequest,
    ZhetaokeBrandResult,
    fetch_brand_products,
)
from .zhetaoke_search_client import ZhetaokeSearchProduct


class ZhetaokeBrandArgs(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=20)
    sort: str = "new"
    cid: int = Field(default=0, ge=0)
    pinpai_name: str = ""
    include_total_count: bool = False


def create_zhetaoke_brand_products_tool(
    appkey: str = "",
    sid: str = "",
    pid: str = "",
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="zhetaoke_brand_products",
        description=(
            "Fetch selected-brand Taobao affiliate goods through Zhetaoke. "
            "Use for brand goods lists with coupon, price, and commission data."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "page": {"type": "integer", "description": "页码，默认 1"},
                "page_size": {"type": "integer", "description": "返回数量，默认 5，最大 20"},
                "sort": {"type": "string", "description": "new、price_asc、tkfee_desc 等"},
                "cid": {"type": "integer", "description": "一级类目 ID，0 表示全部"},
                "pinpai_name": {"type": "string", "description": "品牌名，如 南极人、苏泊尔、美的"},
                "include_total_count": {"type": "boolean", "description": "是否请求总数"},
            },
            required=[],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            params = _parse_args(args)
            result = await fetch_brand_products(
                _load_credentials(appkey, sid, pid),
                ZhetaokeBrandRequest(**params.model_dump()),
            )
            return ToolResult(output=_format_report(params, result))
        except (ValueError, ZhetaokeBrandError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"折淘客精选品牌失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, Any]) -> ZhetaokeBrandArgs:
    try:
        return ZhetaokeBrandArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise ValueError(f"参数错误：{message}") from exc


def _load_credentials(appkey: str, sid: str, pid: str) -> ZhetaokeBrandCredentials:
    return ZhetaokeBrandCredentials(
        appkey=(appkey or os.environ.get("ZHETAOKE_APP_KEY", "")).strip(),
        sid=(sid or os.environ.get("ZHETAOKE_TB_SID", "")).strip(),
        pid=(pid or os.environ.get("ZHETAOKE_TB_PID", "")).strip(),
    )


def _format_report(args: ZhetaokeBrandArgs, result: ZhetaokeBrandResult) -> str:
    label = args.pinpai_name or "精选品牌"
    count_text = f"，总数 {result.total_count}" if result.total_count is not None else ""
    if not result.products:
        return f'折淘客精选品牌: "{label}" 未返回商品数据{count_text}。'
    lines = [f'折淘客精选品牌: "{label}"，返回 {len(result.products)} 个结果{count_text}']
    for index, item in enumerate(result.products, start=1):
        lines.extend(_product_lines(index, item))
    return "\n".join(lines)


def _product_lines(index: int, item: ZhetaokeSearchProduct) -> list[str]:
    return [
        "",
        f"{index}. {item.title or item.long_title or '(未命名商品)'}",
        f"   商品ID: {item.tao_id or '未知'} | 价格: {item.price or '未知'}",
        f"   券后价: {item.coupon_price or '未知'} | 优惠券: {item.coupon_info or '无'}",
        f"   佣金率: {item.commission_rate or '未知'} | 返佣: {item.commission or '未知'}",
        f"   店铺: {item.shop_title or '未知'} | 销量: {item.volume or '未知'}",
        f"   链接: {item.item_url or '无'}",
    ]


__all__ = ["ZhetaokeBrandArgs", "create_zhetaoke_brand_products_tool"]
