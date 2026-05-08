from __future__ import annotations

from backend.common.logging import get_logger
from backend.config import get_redis

logger = get_logger(component="feishu_menu_state")

_MODE_TTL_SECONDS = 7 * 24 * 3600
_CHAT_TTL_SECONDS = 30 * 24 * 3600


class FeishuMenuState:
    def __init__(self) -> None:
        self._user_modes: dict[str, str] = {}
        self._user_chats: dict[str, str] = {}

    async def set_mode(self, open_id: str, mode: str) -> None:
        self._user_modes[open_id] = mode
        redis = get_redis()
        if redis is None:
            return
        try:
            await redis.set(self._mode_key(open_id), mode, ex=_MODE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("feishu_menu_state_set_mode_failed", open_id=open_id, error=str(exc))

    async def clear_mode(self, open_id: str) -> None:
        self._user_modes.pop(open_id, None)
        redis = get_redis()
        if redis is None:
            return
        try:
            await redis.delete(self._mode_key(open_id))
        except Exception as exc:
            logger.warning("feishu_menu_state_clear_mode_failed", open_id=open_id, error=str(exc))

    async def get_mode(self, open_id: str) -> str:
        redis = get_redis()
        if redis is not None:
            try:
                value = await redis.get(self._mode_key(open_id))
                if isinstance(value, str):
                    self._user_modes[open_id] = value
                    return value
            except Exception as exc:
                logger.warning("feishu_menu_state_get_mode_failed", open_id=open_id, error=str(exc))
        return self._user_modes.get(open_id, "")

    async def set_chat(self, open_id: str, chat_id: str) -> None:
        self._user_chats[open_id] = chat_id
        redis = get_redis()
        if redis is None:
            return
        try:
            await redis.set(self._chat_key(open_id), chat_id, ex=_CHAT_TTL_SECONDS)
        except Exception as exc:
            logger.warning("feishu_menu_state_set_chat_failed", open_id=open_id, error=str(exc))

    async def get_chat(self, open_id: str) -> str:
        redis = get_redis()
        if redis is not None:
            try:
                value = await redis.get(self._chat_key(open_id))
                if isinstance(value, str):
                    self._user_chats[open_id] = value
                    return value
            except Exception as exc:
                logger.warning("feishu_menu_state_get_chat_failed", open_id=open_id, error=str(exc))
        return self._user_chats.get(open_id, "")

    @staticmethod
    def _mode_key(open_id: str) -> str:
        return f"feishu:user_mode:{open_id}"

    @staticmethod
    def _chat_key(open_id: str) -> str:
        return f"feishu:user_chat:{open_id}"


__all__ = ["FeishuMenuState"]
