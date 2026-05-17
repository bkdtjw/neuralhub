from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .jd_union_client import (
    JdUnionClientError,
    JdUnionCredentials,
    JdUnionGoods,
    JdUnionSearchRequest,
    search_goods,
)


class JdUnionSearchArgs(BaseModel):
    keyword: str
    max_results: int = Field(default=10, ge=1, le=20)
    page_index: int = Field(default=1, ge=1, le=100)


def create_jd_union_search_tool(
    app_key: str = "",
    app_secret: str = "",
    access_token: str = "",
) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="jd_union_search",
        description=(
            "Search JD Union goods by keyword through the official API. "
            "Use this before browser automation for JD product price/status queries."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "keyword": {"type": "string", "description": "商品搜索关键词，如 iPhone 17"},
                "max_results": {"type": "integer", "description": "最多返回数量，默认 10，最大 20"},
                "page_index": {"type": "integer", "description": "页码，默认 1"},
            },
            required=["keyword"],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            params = _parse_args(args)
            credentials = _load_credentials(app_key, app_secret, access_token)
            goods = await search_goods(
                credentials,
                JdUnionSearchRequest(
                    keyword=params.keyword,
                    page_index=params.page_index,
                    page_size=params.max_results,
                ),
            )
            return ToolResult(output=_format_report(params.keyword, goods))
        except (JdUnionClientError, ValueError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"京东联盟搜索失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, Any]) -> JdUnionSearchArgs:
    try:
        return JdUnionSearchArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise ValueError(f"参数错误：{message}") from exc


def _load_credentials(app_key: str, app_secret: str, access_token: str) -> JdUnionCredentials:
    credentials = JdUnionCredentials(
        app_key=(app_key or os.environ.get("JD_UNION_APP_KEY", "")).strip(),
        app_secret=(app_secret or os.environ.get("JD_UNION_APP_SECRET", "")).strip(),
        access_token=(access_token or os.environ.get("JD_UNION_ACCESS_TOKEN", "")).strip(),
    )
    if not credentials.app_key or not credentials.app_secret:
        raise JdUnionClientError("请配置 JD_UNION_APP_KEY 和 JD_UNION_APP_SECRET")
    return credentials


def _format_report(keyword: str, goods: list[JdUnionGoods]) -> str:
    header = f'京东联盟商品搜索: "{keyword}"，返回 {len(goods)} 个结果'
    if not goods:
        return f"{header}\n\n未找到商品，或当前应用没有该接口权限。"
    lines = [header]
    for index, item in enumerate(goods, start=1):
        title = item.title or "(未命名商品)"
        price = item.price or "未知"
        commission = item.commission or "未知"
        shop = item.shop_name or "未知店铺"
        lines.extend(
            [
                "",
                f"{index}. {title}",
                f"   SKU: {item.sku_id or '未知'} | 价格: {price} | 佣金: {commission}",
                f"   店铺: {shop}",
                f"   链接: {item.url or '无'}",
            ]
        )
    return "\n".join(lines)


__all__ = ["JdUnionSearchArgs", "create_jd_union_search_tool"]
