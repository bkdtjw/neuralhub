from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SiteConfig

from .models import Article, ImageRef

logger = get_logger(component="article_fallback")
_SKIP_TAGS = {"script", "style", "noscript", "svg"}


class _ArticleParser(HTMLParser):
    def __init__(self, selectors: list[str], base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors
        self.base_url = base_url
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.images: list[ImageRef] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        self.stack.append((tag, attrs_dict))
        if tag == "title" or _matches_any(tag, attrs_dict, self.selectors):
            self._in_title = tag == "title"
        if tag == "img":
            self._add_image(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in _SKIP_TAGS for tag, _ in self.stack):
            return
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._inside_content():
            self.body_parts.append(text)

    def _inside_content(self) -> bool:
        if not self.selectors:
            return any(tag == "body" for tag, _ in self.stack)
        return any(_matches_any(tag, attrs, self.selectors) for tag, attrs in self.stack)

    def _add_image(self, attrs: dict[str, str]) -> None:
        src = attrs.get("src") or attrs.get("data-src") or ""
        if not src:
            return
        self.images.append(
            ImageRef(
                url=urljoin(self.base_url, src),
                width=_parse_int(attrs.get("width", "")),
                height=_parse_int(attrs.get("height", "")),
                alt=attrs.get("alt", ""),
                parent_selectors=[_selector_for(tag, item) for tag, item in self.stack],
            )
        )


async def extract_with_selectors(html: str, url: str, config: SiteConfig) -> Article:
    try:
        parser = _ArticleParser(config.content_selectors, url)
        parser.feed(html)
        title = _first_non_empty(parser.title_parts) or _title_from_html(html)
        body = "\n".join(parser.body_parts).strip()
        if not body:
            body = _body_from_html(html)
        return Article(
            url=url,
            title=title or url,
            body=body,
            images=parser.images,
            source="fallback",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("fallback_extract_failed", url=url, error=str(exc))
        raise AgentError("ARTICLE_FALLBACK_EXTRACT_ERROR", str(exc)) from exc


def _matches_any(tag: str, attrs: dict[str, str], selectors: list[str]) -> bool:
    return any(_matches(tag, attrs, selector.strip()) for selector in selectors if selector.strip())


def _matches(tag: str, attrs: dict[str, str], selector: str) -> bool:
    if selector.startswith("#"):
        return attrs.get("id") == selector[1:]
    if selector.startswith("."):
        return selector[1:] in attrs.get("class", "").split()
    return tag == selector.lower()


def _selector_for(tag: str, attrs: dict[str, str]) -> str:
    if attrs.get("id"):
        return f"#{attrs['id']}"
    if attrs.get("class"):
        return f".{attrs['class'].split()[0]}"
    return tag


def _parse_int(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _first_non_empty(values: list[str]) -> str:
    return next((value for value in values if value.strip()), "")


def _title_from_html(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return _clean_text(match.group(1)) if match else ""


def _body_from_html(html: str) -> str:
    text = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


__all__ = ["extract_with_selectors"]
