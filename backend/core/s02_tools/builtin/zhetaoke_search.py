from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .zhetaoke_search_client import (
    ZhetaokeSearchCredentials,
    ZhetaokeSearchError,
    ZhetaokeSearchProduct,
    ZhetaokeSearchRequest,
    search_taobao_products,
)


class ZhetaokeTaobaoSearchArgs(BaseModel):
    q: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=20)
    sort: str = "new"
    youquan: str = ""
    tj: str = ""
    start_tk_rate: str = ""
    end_tk_rate: str = ""
    start_price: str = ""
    end_price: str = ""
    filter_type: str = "2"


def create_zhetaoke_taobao_search_tool(
    appkey: str = "",
    sid: str = "",
    pid: str = "",
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="zhetaoke_taobao_search",
        description=(
            "Search Taobao affiliate goods through Zhetaoke full-network search. "
            "Use for Taobao coupon, price, commission, and product list queries."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "q": {"type": "string", "description": "关键词、店铺名或商品明文链接"},
                "page": {"type": "integer", "description": "页码，默认 1"},
                "page_size": {"type": "integer", "description": "返回数量，默认 5，最大 20"},
                "sort": {"type": "string", "description": "new、price_asc、commission_rate_desc 等"},
                "youquan": {"type": "string", "description": "1 只看有券商品"},
                "tj": {"type": "string", "description": "tmall 只看天猫商品"},
                "start_tk_rate": {"type": "string", "description": "佣金率下限，如 20"},
                "end_tk_rate": {"type": "string", "description": "佣金率上限，如 50"},
                "start_price": {"type": "string", "description": "折扣价下限"},
                "end_price": {"type": "string", "description": "折扣价上限"},
                "filter_type": {"type": "string", "description": "0 不过滤，1 轻度，2 中度，默认 2"},
            },
            required=[],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            params = _parse_args(args)
            products = await search_taobao_products(
                _load_credentials(appkey, sid, pid),
                ZhetaokeSearchRequest(**params.model_dump()),
            )
            return ToolResult(output=_format_report(params.q, products))
        except (ValueError, ZhetaokeSearchError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"折淘客淘宝搜索失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, Any]) -> ZhetaokeTaobaoSearchArgs:
    try:
        return ZhetaokeTaobaoSearchArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise ValueError(f"参数错误：{message}") from exc


def _load_credentials(appkey: str, sid: str, pid: str) -> ZhetaokeSearchCredentials:
    return ZhetaokeSearchCredentials(
        appkey=(appkey or os.environ.get("ZHETAOKE_APP_KEY", "")).strip(),
        sid=(sid or os.environ.get("ZHETAOKE_TB_SID", "")).strip(),
        pid=(pid or os.environ.get("ZHETAOKE_TB_PID", "")).strip(),
    )


def _format_report(keyword: str, products: list[ZhetaokeSearchProduct]) -> str:
    label = keyword or "全网商品"
    if not products:
        return f'折淘客淘宝搜索: "{label}" 未返回商品数据。'
    lines = [f'折淘客淘宝搜索: "{label}"，返回 {len(products)} 个结果']
    for index, item in enumerate(products, start=1):
        lines.extend(
            [
                "",
                f"{index}. {item.title or item.long_title or '(未命名商品)'}",
                f"   商品ID: {item.tao_id or '未知'} | 价格: {item.price or '未知'}",
                f"   券后价: {item.coupon_price or '未知'} | 优惠券: {item.coupon_info or '无'}",
                f"   佣金率: {item.commission_rate or '未知'} | 返佣: {item.commission or '未知'}",
                f"   店铺: {item.shop_title or '未知'} | 销量: {item.volume or '未知'}",
                f"   链接: {item.item_url or '无'}",
            ]
        )
    return "\n".join(lines)


__all__ = ["ZhetaokeTaobaoSearchArgs", "create_zhetaoke_taobao_search_tool"]
