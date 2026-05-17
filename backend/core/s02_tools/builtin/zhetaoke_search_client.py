from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from backend.config.http_client import load_http_client_config
from backend.core.s02_tools.builtin.youtube_log_filter import install_httpx_api_key_redaction

ZHETAOKE_SEARCH_URL = "https://api.zhetaoke.com:10003/api/api_quanwang.ashx"
ZHETAOKE_SEARCH_BACKUP_URL = "http://api.zhetaoke.cn:10000/api/api_quanwang.ashx"
install_httpx_api_key_redaction()


class ZhetaokeSearchError(Exception):
    """Zhetaoke search client error."""


class ZhetaokeSearchCredentials(BaseModel):
    appkey: str
    sid: str
    pid: str


class ZhetaokeSearchRequest(BaseModel):
    q: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=50)
    sort: str = "new"
    material_id: str = ""
    youquan: str = ""
    haiwai: str = ""
    haoping: str = ""
    tj: str = ""
    itemloc: str = ""
    need_prepay: str = ""
    cat: str = ""
    start_tk_rate: str = ""
    end_tk_rate: str = ""
    start_price: str = ""
    end_price: str = ""
    filter_type: str = "2"

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
        }
        cleaned = (value or "new").strip()
        if cleaned not in allowed:
            raise ValueError("sort is not supported")
        return cleaned

    @field_validator("filter_type")
    @classmethod
    def validate_filter_type(cls, value: str) -> str:
        cleaned = str(value or "2").strip()
        if cleaned not in {"0", "1", "2"}:
            raise ValueError("filter_type must be 0, 1, or 2")
        return cleaned


class ZhetaokeSearchProduct(BaseModel):
    code: str = ""
    tao_id: str = ""
    title: str = ""
    long_title: str = ""
    image_url: str = ""
    price: str = ""
    coupon_price: str = ""
    coupon_info: str = ""
    coupon_amount: str = ""
    commission_rate: str = ""
    commission: str = ""
    shop_title: str = ""
    item_url: str = ""
    volume: str = ""
    category_name: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


async def search_taobao_products(
    credentials: ZhetaokeSearchCredentials,
    request: ZhetaokeSearchRequest,
    client: httpx.AsyncClient | None = None,
) -> list[ZhetaokeSearchProduct]:
    try:
        _validate_credentials(credentials)
        params = _build_params(credentials, request)
        if client is not None:
            payload = await _request_json(client, params)
        else:
            async with httpx.AsyncClient(
                timeout=12.0,
                trust_env=load_http_client_config().trust_env,
            ) as http_client:
                payload = await _request_json(http_client, params)
        return [_to_product(item) for item in _extract_items(payload)]
    except ZhetaokeSearchError:
        raise
    except httpx.HTTPError as exc:
        raise ZhetaokeSearchError(f"折淘客全网搜索网络请求失败：{exc.__class__.__name__}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ZhetaokeSearchError(f"折淘客全网搜索调用失败：{exc}") from exc


def _validate_credentials(credentials: ZhetaokeSearchCredentials) -> None:
    if not credentials.appkey.strip():
        raise ZhetaokeSearchError("请配置 ZHETAOKE_APP_KEY")
    if not credentials.sid.strip() or not credentials.pid.strip():
        raise ZhetaokeSearchError("请配置 ZHETAOKE_TB_SID 和 ZHETAOKE_TB_PID")


def _build_params(
    credentials: ZhetaokeSearchCredentials,
    request: ZhetaokeSearchRequest,
) -> dict[str, str]:
    params = request.model_dump()
    params["type"] = params.pop("filter_type")
    params.update(
        {
            "appkey": credentials.appkey.strip(),
            "sid": credentials.sid.strip(),
            "pid": credentials.pid.strip(),
            "page": str(request.page),
            "page_size": str(request.page_size),
        }
    )
    return {key: str(value).strip() for key, value in params.items() if str(value).strip()}


async def _request_json(client: httpx.AsyncClient, params: dict[str, str]) -> dict[str, Any]:
    last_error = ""
    for url in (ZHETAOKE_SEARCH_URL, ZHETAOKE_SEARCH_BACKUP_URL):
        try:
            return await _request_json_from_url(client, url, params)
        except ZhetaokeSearchError as exc:
            last_error = str(exc)
    raise ZhetaokeSearchError(last_error or "折淘客全网搜索调用失败")


async def _request_json_from_url(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
) -> dict[str, Any]:
    response = await client.get(url, params=params)
    if response.status_code >= 400:
        raise ZhetaokeSearchError(f"折淘客全网搜索 HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ZhetaokeSearchError("折淘客全网搜索返回不是 JSON object")
    status = int(payload.get("status") or 0)
    if status != 200:
        raise ZhetaokeSearchError(f"折淘客全网搜索错误 {status}")
    return payload


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    content = payload.get("content") or []
    return [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []


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


__all__ = ["ZhetaokeSearchCredentials", "ZhetaokeSearchError", "ZhetaokeSearchProduct", "ZhetaokeSearchRequest", "search_taobao_products"]
