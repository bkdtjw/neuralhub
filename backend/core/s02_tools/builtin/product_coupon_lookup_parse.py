from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from backend.config.http_client import load_http_client_config

from .product_coupon_lookup_models import ExpandedLink, LookupContext, ProductCouponLookupArgs

_URL_RE = re.compile(r"https?://[^\s「」\"'<>]+")
_TITLE_RE = re.compile(r"[「\"]([^「」\"]{4,160})[」\"]")


async def build_lookup_context(args: ProductCouponLookupArgs) -> LookupContext:
    text = " ".join(part for part in [args.text.strip(), args.url.strip()] if part)
    url = args.url.strip() or first_url(text)
    expanded = await expand_url(url) if url else ExpandedLink()
    haystack = "\n".join([text, expanded.final_url, expanded.body])
    platform = resolve_platform(args.platform, haystack)
    item_id = args.item_id.strip() or extract_item_id(platform, haystack)
    title = args.title.strip() or extract_title(text)
    return LookupContext(
        platform=platform,
        input_text=text,
        original_url=url,
        final_url=expanded.final_url or url,
        title=title,
        item_id=item_id,
    )


async def expand_url(url: str) -> ExpandedLink:
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=False,
        trust_env=load_http_client_config().trust_env,
        headers=headers,
    ) as client:
        current = url
        body = ""
        for _ in range(5):
            response = await client.get(current)
            body = response.text[:20000]
            location = response.headers.get("location", "")
            if not location:
                final = extract_target_url(body) or str(response.url)
                return ExpandedLink(original_url=url, final_url=final, body=body)
            current = str(response.url.join(location))
        return ExpandedLink(original_url=url, final_url=current, body=body)


def resolve_platform(requested: str, text: str) -> str:
    if requested in {"taobao", "jd"}:
        return requested
    lowered = text.lower()
    if "【京东】" in text or "京东" in text or "jd.com" in lowered or "3.cn/" in lowered:
        return "jd"
    if any(marker in lowered for marker in ("taobao.com", "tmall.com", "tb.cn", "e.tb.cn")):
        return "taobao"
    if "【淘宝】" in text or "【天猫】" in text or "淘宝" in text or "天猫" in text:
        return "taobao"
    return "unknown"


def first_url(text: str) -> str:
    match = _URL_RE.search(text)
    return match.group(0).rstrip("，。,.") if match else ""


def extract_title(text: str) -> str:
    match = _TITLE_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_target_url(body: str) -> str:
    match = re.search(r"var\s+url\s*=\s*'([^']+)'", body)
    return unquote(match.group(1)) if match else ""


def extract_item_id(platform: str, text: str) -> str:
    decoded = unquote(text)
    patterns = _jd_patterns() if platform == "jd" else _taobao_patterns()
    for pattern in patterns:
        match = re.search(pattern, decoded)
        if match:
            return match.group(1)
    if platform in {"jd", "taobao"}:
        parsed = urlparse(decoded)
        for key in ("id", "skuId", "itemId", "shareDetailItemId"):
            value = parse_qs(parsed.query).get(key, [""])[0]
            if value.isdigit():
                return value
        match = re.search(r"(?<!\d)(\d{6,18})(?!\d)", decoded)
        if match:
            return match.group(1)
    return ""


def _jd_patterns() -> list[str]:
    return [r"/product/(\d{6,})", r"item\.jd\.com/(\d{6,})\.html", r"skuId[=:](\d{6,})"]


def _taobao_patterns() -> list[str]:
    return [r"shareDetailItemId=(\d{6,})", r"[?&]id=(\d{6,})", r"itemId[=:](\d{6,})"]


__all__ = [
    "build_lookup_context",
    "expand_url",
    "extract_item_id",
    "extract_title",
    "extract_target_url",
    "first_url",
    "resolve_platform",
]
