from __future__ import annotations

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SiteConfig

from .api_adapters.hn import fetch_hn_article
from .api_adapters.rss import fetch_rss_article
from .extract_fallback import extract_with_selectors
from .extract_trafilatura import extract_with_trafilatura
from .models import Article

logger = get_logger(component="article_extractor")


async def extract_article(html: str, url: str, site_config: SiteConfig | None = None) -> Article:
    config = site_config or SiteConfig()
    try:
        api_article = await _extract_from_api(url, config)
        if api_article is not None:
            return api_article

        trafilatura_article = await extract_with_trafilatura(html, url)
        if trafilatura_article is not None and trafilatura_article.body:
            return trafilatura_article

        return await extract_with_selectors(html, url, config)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("article_extract_failed", url=url, error=str(exc))
        raise AgentError("ARTICLE_EXTRACT_ERROR", str(exc)) from exc


async def _extract_from_api(url: str, config: SiteConfig) -> Article | None:
    try:
        if config.api_kind == "hn":
            return await fetch_hn_article(url)
        if config.rss_url:
            return await fetch_rss_article(config.rss_url, url)
        return None
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("article_api_extract_failed", url=url, error=str(exc))
        raise AgentError("ARTICLE_API_EXTRACT_ERROR", str(exc)) from exc


__all__ = ["extract_article"]
