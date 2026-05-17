from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .zhetaoke_client import (
    ZhetaokeClientError,
    ZhetaokeCredentials,
    ZhetaokeDetailRequest,
    ZhetaokeProduct,
    fetch_product_detail,
)


class ZhetaokeDetailArgs(BaseModel):
    tao_id: str = ""
    num_iids: str = ""
    code: str = ""
    detail_type: str = Field(default="1")

    @model_validator(mode="after")
    def validate_ids(self) -> ZhetaokeDetailArgs:
        if not self.tao_id.strip() and not self.num_iids.strip():
            raise ValueError("tao_id or num_iids is required")
        return self


def create_zhetaoke_product_detail_tool(appkey: str = "") -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="zhetaoke_product_detail",
        description=(
            "Fetch Zhetaoke Taobao affiliate product detail and coupon information. "
            "Use when a Taobao item URL is known; numeric-only item ids may be rejected by the API."
        ),
        category="search",
        parameters=ToolParameterSchema(
            properties={
                "tao_id": {"type": "string", "description": "单个淘宝商品链接，优先传完整 URL"},
                "num_iids": {"type": "string", "description": "多个站内商品 ID，逗号分隔，最多 40 个"},
                "code": {"type": "string", "description": "可选折淘客编号，需与 tao_id 对应"},
                "detail_type": {"type": "string", "description": "0 返回 S/G 券全部；1 返回单条，默认 1"},
            },
            required=[],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            params = _parse_args(args)
            products = await fetch_product_detail(
                _load_credentials(appkey),
                ZhetaokeDetailRequest(
                    tao_id=params.tao_id,
                    num_iids=params.num_iids,
                    code=params.code,
                    detail_type=params.detail_type,
                ),
            )
            return ToolResult(output=_format_report(products))
        except (ValueError, ZhetaokeClientError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"折京客商品详情失败：{exc}", is_error=True)

    return definition, execute


def _parse_args(args: dict[str, Any]) -> ZhetaokeDetailArgs:
    try:
        return ZhetaokeDetailArgs.model_validate(args)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "参数不合法")
        raise ValueError(f"参数错误：{message}") from exc


def _load_credentials(appkey: str) -> ZhetaokeCredentials:
    resolved = (appkey or os.environ.get("ZHETAOKE_APP_KEY", "")).strip()
    if not resolved:
        raise ZhetaokeClientError("请配置 ZHETAOKE_APP_KEY")
    return ZhetaokeCredentials(
        appkey=resolved,
        sid=os.environ.get("ZHETAOKE_TB_SID", "").strip(),
        pid=os.environ.get("ZHETAOKE_TB_PID", "").strip(),
    )


def _format_report(products: list[ZhetaokeProduct]) -> str:
    if not products:
        return "折淘客商品详情：未返回商品数据。"
    lines = [f"折淘客商品详情：返回 {len(products)} 条记录"]
    for index, item in enumerate(products, start=1):
        lines.extend(
            [
                "",
                f"{index}. {item.title or item.long_title or '(未命名商品)'}",
                f"   商品ID: {item.tao_id or '未知'} | 编号: {item.code or '无'}",
                f"   原价/折扣价: {item.price or '未知'} | 券后价: {item.coupon_price or '未知'}",
                f"   优惠券: {item.coupon_info or '无'} | 券金额: {item.coupon_amount or '无'}",
                f"   佣金率: {item.commission_rate or '未知'} | 返佣: {item.commission or '未知'}",
                f"   店铺: {item.shop_title or '未知'} | 好评率: {item.good_rate or '未知'}",
                f"   链接: {item.item_url or '无'}",
            ]
        )
    return "\n".join(lines)


__all__ = ["ZhetaokeDetailArgs", "create_zhetaoke_product_detail_tool"]
