from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="browser_ad_blocker")

BLOCKLIST_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "hotjar.com",
    "scorecardresearch.com",
)


async def install_route_blocker(page: Any, extra_domains: Iterable[str] | None = None) -> None:
    try:
        domains = {domain.lower() for domain in BLOCKLIST_DOMAINS}
        domains.update(domain.lower() for domain in (extra_domains or []) if domain)

        async def _handle_route(route: Any, request: Any) -> None:
            try:
                request_url = str(getattr(request, "url", "")).lower()
                if any(domain in request_url for domain in domains):
                    await route.abort()
                    return
                await route.continue_()
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_route_blocker_error", error=str(exc))
                try:
                    await route.continue_()
                except Exception as continue_exc:  # noqa: BLE001
                    logger.error("browser_route_continue_failed", error=str(continue_exc))

        await page.route("**/*", _handle_route)
    except Exception as exc:  # noqa: BLE001
        logger.error("browser_route_blocker_install_failed", error=str(exc))
        raise AgentError("BROWSER_ROUTE_BLOCKER_ERROR", str(exc)) from exc


__all__ = ["BLOCKLIST_DOMAINS", "install_route_blocker"]
