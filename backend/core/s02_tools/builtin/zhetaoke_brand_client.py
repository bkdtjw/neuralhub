from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from backend.config.http_client import load_http_client_config
from backend.core.s02_tools.builtin.youtube_log_filter import install_httpx_api_key_redaction
from backend.core.s02_tools.builtin.zhetaoke_search_client import ZhetaokeSearchProduct

ZHETAOKE_BRAND_URL = "https://api.zhetaoke.com:10001/api/api_all.ashx"
ZHETAOKE_BRAND_BACKUP_URL = "http://api.zhetaoke.cn:10000/api/api_all.ashx"
install_httpx_api_key_redaction()


class ZhetaokeBrandError(Exception):
    """Zhetaoke brand product client error."""


class ZhetaokeBrandCredentials(BaseModel):
    appkey: str
    sid: str = ""
    pid: str = ""


class ZhetaokeBrandRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=50)
    sort: str = "new"
    cid: int = Field(default=0, ge=0)
    pinpai_name: str = ""
    include_total_count: bool = False

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, value: str) -> str:
        allowed = {
            "new",
            "total_sale_num_asc",
            "total_sale_num_desc",
            "sale_num_asc",
            "sale_num_desc",
            "commission_rate_asc",
            "commission_rate_desc",
            "price_asc",
            "price_desc",
            "coupon_info_money_asc",
            "coupon_info_money_desc",
            "shop_level_asc",
            "shop_level_desc",
            "tkfee_asc",
            "tkfee_desc",
            "code",
            "date_time",
            "random",
        }
        cleaned = (value or "new").strip()
        if cleaned not in allowed:
            raise ValueError("sort is not supported")
        return cleaned


class ZhetaokeBrandResult(BaseModel):
    products: list[ZhetaokeSearchProduct] = Field(default_factory=list)
    total_count: int | None = None


async def fetch_brand_products(
    credentials: ZhetaokeBrandCredentials,
    request: ZhetaokeBrandRequest,
    client: httpx.AsyncClient | None = None,
) -> ZhetaokeBrandResult:
    try:
        if not credentials.appkey.strip():
            raise ZhetaokeBrandError("请配置 ZHETAOKE_APP_KEY")
        params = _build_params(credentials, request)
        if client is not None:
            payload = await _request_json(client, params)
        else:
            async with httpx.AsyncClient(
                timeout=12.0,
                trust_env=load_http_client_config().trust_env,
            ) as http_client:
                payload = await _request_json(http_client, params)
        return _to_result(payload)
    except ZhetaokeBrandError:
        raise
    except httpx.HTTPError as exc:
        raise ZhetaokeBrandError(f"折淘客精选品牌网络请求失败：{exc.__class__.__name__}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ZhetaokeBrandError(f"折淘客精选品牌调用失败：{exc}") from exc


def _build_params(
    credentials: ZhetaokeBrandCredentials,
    request: ZhetaokeBrandRequest,
) -> dict[str, str]:
    params = {
        "appkey": credentials.appkey.strip(),
        "sid": credentials.sid.strip(),
        "pid": credentials.pid.strip(),
        "page": str(request.page),
        "page_size": str(request.page_size),
        "sort": request.sort,
        "cid": str(request.cid),
        "pinpai": "1",
        "pinpai_name": request.pinpai_name.strip(),
        "total_count": "1" if request.include_total_count else "",
    }
    return {key: value for key, value in params.items() if value}


async def _request_json(client: httpx.AsyncClient, params: dict[str, str]) -> dict[str, Any]:
    last_error = ""
    for url in (ZHETAOKE_BRAND_URL, ZHETAOKE_BRAND_BACKUP_URL):
        try:
            return await _request_json_from_url(client, url, params)
        except ZhetaokeBrandError as exc:
            last_error = str(exc)
    raise ZhetaokeBrandError(last_error or "折淘客精选品牌调用失败")


async def _request_json_from_url(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
) -> dict[str, Any]:
    response = await client.get(url, params=params)
    if response.status_code >= 400:
        raise ZhetaokeBrandError(f"折淘客精选品牌 HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ZhetaokeBrandError("折淘客精选品牌返回不是 JSON object")
    status = int(payload.get("status") or 0)
    if status != 200:
        raise ZhetaokeBrandError(f"折淘客精选品牌错误 {status}")
    return payload


def _to_result(payload: dict[str, Any]) -> ZhetaokeBrandResult:
    content = payload.get("content") or []
    items = content if isinstance(content, list) else []
    return ZhetaokeBrandResult(
        products=[_to_product(item) for item in items if isinstance(item, dict)],
        total_count=_parse_total_count(payload.get("total_count")),
    )


def _parse_total_count(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_product(item: dict[str, Any]) -> ZhetaokeSearchProduct:
    return ZhetaokeSearchProduct(
        code=str(item.get("code") or ""),
        tao_id=str(item.get("tao_id") or ""),
        title=str(item.get("title") or ""),
        long_title=str(item.get("tao_title") or ""),
        image_url=str(item.get("pict_url") or ""),
        price=str(item.get("size") or ""),
        coupon_price=str(item.get("quanhou_jiage") or ""),
        coupon_info=str(item.get("coupon_info") or ""),
        coupon_amount=str(item.get("coupon_info_money") or ""),
        commission_rate=str(item.get("tkrate3") or ""),
        commission=str(item.get("tkfee3") or ""),
        shop_title=str(item.get("shop_title") or item.get("nick") or ""),
        item_url=str(item.get("item_url") or ""),
        volume=str(item.get("volume") or item.get("sellCount") or ""),
        category_name=str(item.get("category_name") or ""),
        raw=item,
    )


__all__ = [
    "ZhetaokeBrandCredentials",
    "ZhetaokeBrandError",
    "ZhetaokeBrandRequest",
    "ZhetaokeBrandResult",
    "fetch_brand_products",
]
