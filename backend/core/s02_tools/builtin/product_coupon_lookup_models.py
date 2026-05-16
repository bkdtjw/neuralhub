from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Platform = Literal["auto", "taobao", "jd"]


class ProductCouponLookupConfig(BaseModel):
    zhetaoke_appkey: str = ""
    zhetaoke_sid: str = ""
    zhetaoke_pid: str = ""
    jd_app_key: str = ""
    jd_app_secret: str = ""
    jd_access_token: str = ""


class ProductCouponLookupArgs(BaseModel):
    text: str = ""
    url: str = ""
    platform: Platform = "auto"
    title: str = ""
    item_id: str = ""
    max_results: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def validate_input(self) -> ProductCouponLookupArgs:
        if not any((self.text.strip(), self.url.strip(), self.title.strip(), self.item_id.strip())):
            raise ValueError("text, url, title or item_id is required")
        return self


class ExpandedLink(BaseModel):
    original_url: str = ""
    final_url: str = ""
    body: str = ""


class LookupContext(BaseModel):
    platform: Literal["taobao", "jd", "unknown"] = "unknown"
    input_text: str = ""
    original_url: str = ""
    final_url: str = ""
    title: str = ""
    item_id: str = ""


class LookupItem(BaseModel):
    source: str
    match_type: Literal["exact", "similar"] = "exact"
    title: str = ""
    item_id: str = ""
    price: str = ""
    coupon_price: str = ""
    coupon_info: str = ""
    shop: str = ""
    volume: str = ""
    url: str = ""
    note: str = ""


__all__ = [
    "ExpandedLink",
    "LookupContext",
    "LookupItem",
    "Platform",
    "ProductCouponLookupArgs",
    "ProductCouponLookupConfig",
]
