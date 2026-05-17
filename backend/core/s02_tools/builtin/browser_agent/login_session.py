from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SmartPage
from backend.core.s02_tools.builtin.feishu_cards import (
    build_password_card,
    build_sms_code_card,
    build_sms_phone_card,
)

from .login_page import request_sms_code, submit_password, submit_sms_code, wait_login_result
from .login_session_models import LoginAssistResult, LoginCardInput
from .login_vision import LoginVisionHelper

logger = get_logger(component="browser_login_session")


class BrowserLoginSessionManager:
    def __init__(self) -> None:
        self._client: Any = None
        self._sessions: dict[str, asyncio.Queue[LoginCardInput]] = {}
        self._message_sessions: dict[str, str] = {}

    def configure(self, feishu_client: Any) -> None:
        self._client = feishu_client

    def for_chat(self, chat_id: str) -> BrowserLoginAssistant:
        return BrowserLoginAssistant(self, chat_id)

    async def submit(
        self,
        action_type: str,
        session_id: str,
        values: dict[str, str],
    ) -> bool:
        queue = self._sessions.get(session_id)
        if queue is None:
            return False
        await queue.put(LoginCardInput(action_type=action_type, values=values))
        return True

    async def assist(
        self,
        page: SmartPage,
        chat_id: str,
        site: str,
        reason: str = "",
        timeout_seconds: float = 180.0,
        vision_helper: LoginVisionHelper | None = None,
    ) -> LoginAssistResult:
        if self._client is None or not chat_id:
            return LoginAssistResult(status="unavailable", detail="飞书登录卡片未配置")
        session_id = secrets.token_hex(8)
        queue: asyncio.Queue[LoginCardInput] = asyncio.Queue()
        self._sessions[session_id] = queue
        try:
            await self._send_card(chat_id, build_sms_phone_card(site, session_id, reason), session_id)
            return await self._event_loop(
                page, chat_id, site, session_id, queue, timeout_seconds, vision_helper
            )
        finally:
            self._sessions.pop(session_id, None)
            self._message_sessions = {
                message_id: stored
                for message_id, stored in self._message_sessions.items()
                if stored != session_id
            }

    def session_for_message(self, message_id: str) -> str:
        return self._message_sessions.get(message_id, "")

    async def _event_loop(
        self,
        page: SmartPage,
        chat_id: str,
        site: str,
        session_id: str,
        queue: asyncio.Queue[LoginCardInput],
        timeout_seconds: float,
        vision_helper: LoginVisionHelper | None,
    ) -> LoginAssistResult:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                return LoginAssistResult(status="timeout", detail="等待登录信息超时")
            if item.action_type == "browser_login_cancel":
                return LoginAssistResult(status="cancelled", detail="用户取消登录")
            if item.action_type == "browser_login_sms_open":
                await self._send_card(chat_id, build_sms_phone_card(site, session_id), session_id)
                continue
            if item.action_type == "browser_login_password_open":
                await self._send_card(chat_id, build_password_card(site, session_id), session_id)
                continue
            if item.action_type == "browser_login_sms_request":
                phone = item.values.get("phone", "").strip()
                if not phone:
                    await self._send_card(
                        chat_id,
                        build_sms_phone_card(site, session_id, "缺少手机号"),
                        session_id,
                    )
                    continue
                sms_result = await request_sms_code(page, phone, vision_helper)
                logger.info(
                    "browser_login_sms_request_result",
                    status=sms_result.status,
                    detail=sms_result.detail,
                    site=site,
                )
                if sms_result.status == "sent":
                    await self._send_card(
                        chat_id,
                        build_sms_code_card(site, session_id, _mask_phone(phone)),
                        session_id,
                    )
                    continue
                return LoginAssistResult(
                    status=sms_result.status,
                    detail=sms_result.detail or "未能在当前页面触发短信验证码",
                )
            if item.action_type == "browser_login_sms_submit":
                await submit_sms_code(page, item.values.get("code", "").strip())
                return await wait_login_result(page)
            if item.action_type == "browser_login_password_submit":
                await submit_password(
                    page,
                    item.values.get("account", "").strip(),
                    item.values.get("password", ""),
                )
                return await wait_login_result(page)
        return LoginAssistResult(status="timeout", detail="等待登录信息超时")

    async def _send_card(self, chat_id: str, card: dict, session_id: str) -> None:
        message_id = await self._client.send_card(chat_id, card)
        if message_id:
            self._message_sessions[str(message_id)] = session_id


class BrowserLoginAssistant:
    def __init__(self, manager: BrowserLoginSessionManager, chat_id: str) -> None:
        self._manager = manager
        self._chat_id = chat_id

    async def assist(
        self,
        page: SmartPage,
        site: str,
        reason: str = "",
        vision_helper: LoginVisionHelper | None = None,
    ) -> LoginAssistResult:
        return await self._manager.assist(page, self._chat_id, site, reason, vision_helper=vision_helper)


def _mask_phone(phone: str) -> str:
    return f"（尾号 {phone[-4:]}）" if len(phone) >= 4 else ""


browser_login_manager = BrowserLoginSessionManager()

__all__ = ["BrowserLoginAssistant", "BrowserLoginSessionManager", "browser_login_manager"]
