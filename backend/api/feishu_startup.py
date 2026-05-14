from __future__ import annotations

from fastapi import FastAPI

from backend.adapters.provider_manager import ProviderManager
from backend.api.routes.browser_login_card_action import register_browser_login_card_actions
from backend.api.routes.feishu import set_handler
from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.common.logging import get_logger
from backend.config import settings as app_settings
from backend.core.s02_tools.builtin.browser_agent.login_session import browser_login_manager
from backend.core.s02_tools.builtin.feishu_client import FeishuClient

logger = get_logger(component="feishu_startup")


def init_feishu_handler(app: FastAPI) -> None:
    if not app_settings.feishu_app_id or not app_settings.feishu_app_secret:
        return
    client = FeishuClient(
        app_id=app_settings.feishu_app_id,
        app_secret=app_settings.feishu_app_secret,
    )
    browser_login_manager.configure(client)
    register_browser_login_card_actions()
    handler = FeishuMessageHandler(client, ProviderManager())
    handler.configure_runtime(
        getattr(app.state, "agent_runtime", None),
        getattr(app.state, "spec_registry", None),
        getattr(app.state, "task_queue", None),
    )
    set_handler(handler)
    logger.info("feishu_handler_initialized")


__all__ = ["init_feishu_handler"]
