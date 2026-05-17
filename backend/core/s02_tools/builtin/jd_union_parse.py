from __future__ import annotations

import json
from typing import Any


def extract_error(payload: dict[str, Any]) -> str:
    gateway = payload.get("error_response")
    if isinstance(gateway, dict):
        code = str(gateway.get("code", "")).strip()
        desc = str(gateway.get("zh_desc") or gateway.get("en_desc") or gateway.get("msg") or "")
        return f"京东联盟 API 错误 {code}: {desc}".strip()
    return _find_business_error(parse_json_strings(payload))


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lists = _find_product_lists(parse_json_strings(payload))
    return lists[0] if lists else []


def parse_json_strings(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in {"{", "["}:
        try:
            return parse_json_strings(json.loads(value))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {str(key): parse_json_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [parse_json_strings(item) for item in value]
    return value


def _find_business_error(value: Any) -> str:
    if isinstance(value, dict):
        code = str(value.get("code", "")).strip()
        message = str(value.get("message") or value.get("msg") or "").strip()
        if code and code not in {"0", "200"} and message:
            return f"京东联盟 API 错误 {code}: {message}"
        for item in value.values():
            error = _find_business_error(item)
            if error:
                return error
    if isinstance(value, list):
        for item in value:
            error = _find_business_error(item)
            if error:
                return error
    return ""


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
    keys = {"skuId", "skuName", "goodsName", "materialUrl", "priceInfo", "commissionInfo"}
    return bool(keys & item.keys())


__all__ = ["extract_error", "extract_items", "parse_json_strings"]
