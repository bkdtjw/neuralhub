from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from backend.config.http_client import load_http_client_config

JD_UNION_URL = "https://api.jd.com/routerjson"


class JdUnionClientError(Exception):
    """JD Union client error."""

class JdUnionCredentials(BaseModel):
    app_key: str
    app_secret: str
    access_token: str = ""

class JdUnionSearchRequest(BaseModel):
    keyword: str
    page_index: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=10, ge=1, le=50)
    method: str = "jd.union.open.goods.query"

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        keyword = value.strip()
        if not keyword:
            raise ValueError("keyword is required")
        return keyword


class JdUnionGoods(BaseModel):
    sku_id: str = ""
    title: str = ""
    price: str = ""
    commission: str = ""
    shop_name: str = ""
    url: str = ""
    image_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

async def search_goods(
    credentials: JdUnionCredentials,
    request: JdUnionSearchRequest,
    client: httpx.AsyncClient | None = None,
) -> list[JdUnionGoods]:
    try:
        if not credentials.app_key.strip() or not credentials.app_secret.strip():
            raise JdUnionClientError("JD_UNION_APP_KEY and JD_UNION_APP_SECRET are required")
        params = _build_params(credentials, request)
        if client is not None:
            payload = await _request_json(client, params)
        else:
            async with httpx.AsyncClient(
                timeout=12.0,
                trust_env=load_http_client_config().trust_env,
            ) as http_client:
                payload = await _request_json(http_client, params)
        return [_to_goods(item) for item in _extract_items(payload)][: request.page_size]
    except JdUnionClientError:
        raise
    except httpx.HTTPError as exc:
        raise JdUnionClientError(f"京东联盟 API 网络请求失败：{exc.__class__.__name__}") from exc
    except Exception as exc:  # noqa: BLE001
        raise JdUnionClientError(f"京东联盟 API 调用失败：{exc}") from exc


def _build_params(
    credentials: JdUnionCredentials,
    request: JdUnionSearchRequest,
) -> dict[str, str]:
    goods_req = {
        "goodsReqDTO": {
            "keyword": request.keyword,
            "pageIndex": request.page_index,
            "pageSize": request.page_size,
        }
    }
    params = {
        "method": request.method,
        "app_key": credentials.app_key.strip(),
        "access_token": credentials.access_token.strip(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "360buy_param_json": json.dumps(goods_req, ensure_ascii=False, separators=(",", ":")),
    }
    params["sign"] = _sign_params(params, credentials.app_secret.strip())
    return params


def _sign_params(params: dict[str, str], app_secret: str) -> str:
    body = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    return hashlib.md5(f"{app_secret}{body}{app_secret}".encode("utf-8")).hexdigest().upper()


async def _request_json(client: httpx.AsyncClient, params: dict[str, str]) -> dict[str, Any]:
    response = await client.get(JD_UNION_URL, params=params)
    if response.status_code >= 400:
        raise JdUnionClientError(f"京东联盟 API HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise JdUnionClientError("京东联盟 API 返回不是 JSON object")
    error = _extract_error(payload)
    if error:
        raise JdUnionClientError(error)
    return payload


def _extract_error(payload: dict[str, Any]) -> str:
    error = payload.get("error_response")
    if not isinstance(error, dict):
        return ""
    code = str(error.get("code", "")).strip()
    desc = str(error.get("zh_desc") or error.get("en_desc") or error.get("msg") or "").strip()
    return f"京东联盟 API 错误 {code}: {desc}".strip()


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = _parse_json_strings(payload)
    lists = _find_product_lists(parsed)
    return lists[0] if lists else []

def _parse_json_strings(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in {"{", "["}:
        try:
            return _parse_json_strings(json.loads(value))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {str(key): _parse_json_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_parse_json_strings(item) for item in value]
    return value


def _find_product_lists(value: Any) -> list[list[dict[str, Any]]]:
    if isinstance(value, list):
        dict_items = [item for item in value if isinstance(item, dict)]
        if dict_items and any(_looks_like_product(item) for item in dict_items):
            return [dict_items]
        return [found for item in value for found in _find_product_lists(item)]
    if isinstance(value, dict):
        return [found for item in value.values() for found in _find_product_lists(item)]
    return []


def _looks_like_product(item: dict[str, Any]) -> bool:
    return bool(
        {"skuId", "skuName", "goodsName", "materialUrl", "priceInfo", "commissionInfo"} & item.keys()
    )


def _to_goods(item: dict[str, Any]) -> JdUnionGoods:
    return JdUnionGoods(
        sku_id=str(item.get("skuId") or item.get("sku_id") or ""),
        title=str(item.get("skuName") or item.get("goodsName") or item.get("wareName") or ""),
        price=_nested_text(item, "priceInfo", "price"),
        commission=_nested_text(item, "commissionInfo", "commission"),
        shop_name=_nested_text(item, "shopInfo", "shopName"),
        url=str(item.get("materialUrl") or item.get("url") or ""),
        image_url=_image_url(item),
        raw=item,
    )


def _nested_text(item: dict[str, Any], parent: str, child: str) -> str:
    value = item.get(parent)
    if isinstance(value, dict):
        return str(value.get(child) or "")
    return ""


def _image_url(item: dict[str, Any]) -> str:
    image_info = item.get("imageInfo")
    if not isinstance(image_info, dict):
        return ""
    image_list = image_info.get("imageList")
    if not isinstance(image_list, list) or not image_list:
        return ""
    first = image_list[0]
    return str(first.get("url") or "") if isinstance(first, dict) else ""


__all__ = [
    "JdUnionClientError",
    "JdUnionCredentials",
    "JdUnionGoods",
    "JdUnionSearchRequest",
    "search_goods",
]
