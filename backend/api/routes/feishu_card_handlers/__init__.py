from __future__ import annotations

from typing import Any

from backend.api.routes.feishu_events import register_handler

from .models import CardHandlerDeps, parse_action_route
from .relogin_handlers import handle_relogin_done, handle_relogin_start, handle_skip_site
from .selector_handler import handle_provide_selector


def register_all(deps: CardHandlerDeps | None = None) -> None:
    resolved = deps or CardHandlerDeps()

    async def handle_card_action(payload: dict[str, Any]) -> dict[str, Any] | None:
        route = parse_action_route(payload)
        if route.prefix == "relogin_start":
            return await handle_relogin_start(route, resolved)
        if route.prefix == "relogin_done":
            return await handle_relogin_done(route, resolved)
        if route.prefix == "skip_site":
            return await handle_skip_site(route, resolved)
        if route.prefix == "provide_selector":
            return await handle_provide_selector(route, resolved)
        return {"status": "ignored", "action_type": route.action_type}

    register_handler("card.action.trigger", handle_card_action)


__all__ = ["CardHandlerDeps", "register_all"]
