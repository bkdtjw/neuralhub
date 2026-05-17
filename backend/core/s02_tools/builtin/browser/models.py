from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SiteConfig(BaseModel):
    name: str = ""
    user_id: str = "default"
    domain: str = ""
    storage_state_path: Path | None = None
    screenshot_dir: Path | None = Path("/tmp/agent-studio-browser")
    wait_until: str = "domcontentloaded"
    timeout_ms: int = Field(default=15_000, ge=1_000)
    ad_block_domains: list[str] = Field(default_factory=list)
    popup_close_selectors: list[str] = Field(default_factory=list)
    login_path_fragments: list[str] = Field(
        default_factory=lambda: ["/login", "/signin", "/auth"],
    )
    title_selectors: list[str] = Field(default_factory=list)
    content_selectors: list[str] = Field(default_factory=list)
    image_selectors: list[str] = Field(default_factory=list)
    image_min_width: int = Field(default=200, ge=1)
    image_min_height: int = Field(default=200, ge=1)
    blocked_image_url_keywords: list[str] = Field(
        default_factory=lambda: ["avatar", "icon", "logo", "sprite", "tracking"],
    )
    image_excluded_ancestor_selectors: list[str] = Field(
        default_factory=lambda: ["header", "nav", "footer", "aside"],
    )
    api_kind: str = ""
    api_url: str = ""
    rss_url: str = ""
    probe_url: str = ""
    entry_url: str = ""


class PageResult(BaseModel):
    url: str
    html: str
    screenshot_path: Path | None = None
    login_required: bool = False
    unhandled_popup: bool = False


__all__ = ["PageResult", "SiteConfig"]
