from __future__ import annotations

import pytest

from backend.core.s02_tools.builtin.article_extractor import ImageRef, extract_article
from backend.core.s02_tools.builtin.article_extractor import extractor
from backend.core.s02_tools.builtin.article_extractor.site_registry import _matches_domain
from backend.core.s02_tools.builtin.browser import SiteConfig
from backend.core.s02_tools.builtin.image_filter import filter_images


@pytest.mark.asyncio
async def test_extract_article_fallback_and_filter_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_trafilatura(html: str, url: str) -> None:
        return None

    monkeypatch.setattr(extractor, "extract_with_trafilatura", no_trafilatura)
    html = """
    <html><head><title>Morning</title></head>
      <body>
        <article>
          <h1>Ignored because title exists</h1>
          <p>First paragraph.</p><p>Second paragraph.</p>
          <img src="/hero.png" width="640" height="360" alt="hero">
          <img src="/tiny.png" width="120" height="120" alt="tiny">
        </article>
      </body>
    </html>
    """
    config = SiteConfig(content_selectors=["article"])
    article = await extract_article(html, "https://example.com/post", config)
    assert article.title == "Morning"
    assert "First paragraph" in article.body
    assert article.images[0].url == "https://example.com/hero.png"

    images = filter_images(
        [
            *article.images,
            ImageRef(url="https://example.com/logo.png", width=640, height=360),
            ImageRef(
                url="https://example.com/nav.png",
                width=640,
                height=360,
                parent_selectors=["nav"],
            ),
        ],
        config,
    )
    assert [image.url for image in images] == ["https://example.com/hero.png"]


def test_site_registry_matches_host_boundary() -> None:
    rule = {"domain": "example.com"}
    assert _matches_domain("https://news.example.com/post", rule) is True
    assert _matches_domain("example.com", rule) is True
    assert _matches_domain("badexample.com", rule) is False
