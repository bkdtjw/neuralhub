from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable

from backend.common.logging import get_logger
from backend.core.s01_agent_loop import AgentLoop

from .websocket_support import LoopSettings

logger = get_logger(component="websocket_loop_cache")

# 进程内常驻 AgentLoop 数量上限：每个会话首发消息会创建持完整历史 + ToolRegistry +
# MCP 桥 + compressor 的 loop，断连若不回收会内存只增不减。此值仅作兜底封顶。
MAX_CACHED_LOOPS = 64


class LoopCache:
    """会话 AgentLoop 的 LRU 缓存。

    只负责“存/取/淘汰”这一层纯内存容器逻辑：命中刷新最近使用、存入超限时淘汰最久
    未用且空闲的条目。是否空闲由注入的 is_busy 判定——有在跑任务的会话其 loop 不可
    淘汰（后台 run 仍依赖它）。落库、abort 等副作用交由持有者在拿到淘汰结果后完成，
    使本类保持无 I/O、可纯内存单测。
    """

    def __init__(
        self,
        is_busy: Callable[[str], bool],
        max_loops: int = MAX_CACHED_LOOPS,
    ) -> None:
        self._loops: OrderedDict[str, AgentLoop] = OrderedDict()
        self._settings: dict[str, LoopSettings] = {}
        self._is_busy = is_busy
        self._max_loops = max_loops

    @property
    def loops(self) -> OrderedDict[str, AgentLoop]:
        return self._loops

    @property
    def settings(self) -> dict[str, LoopSettings]:
        return self._settings

    def get(self, session_id: str) -> AgentLoop | None:
        loop = self._loops.get(session_id)
        if loop is not None:
            self._loops.move_to_end(session_id)  # 命中即刷新为最近使用
        return loop

    def get_settings(self, session_id: str) -> LoopSettings | None:
        return self._settings.get(session_id)

    def store(
        self,
        session_id: str,
        loop: AgentLoop,
        settings: LoopSettings,
    ) -> list[tuple[str, AgentLoop]]:
        """存入 loop 与其设置，并按 LRU 淘汰超限且空闲的条目。

        返回被淘汰的 (session_id, loop) 列表，由调用方负责落库与 abort。
        """
        self._loops[session_id] = loop
        self._loops.move_to_end(session_id)
        self._settings[session_id] = settings
        evicted: list[tuple[str, AgentLoop]] = []
        for candidate in list(self._loops.keys()):
            if len(self._loops) <= self._max_loops:
                break
            if candidate == session_id or self._is_busy(candidate):
                continue  # 刚存入的与在跑任务的都不淘汰
            victim = self._loops.pop(candidate, None)
            self._settings.pop(candidate, None)
            if victim is not None:
                evicted.append((candidate, victim))
                logger.info("ws_loop_cache_evicted", session_id=candidate)
        return evicted

    def pop(self, session_id: str) -> AgentLoop | None:
        self._settings.pop(session_id, None)
        return self._loops.pop(session_id, None)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._loops

    def __len__(self) -> int:
        return len(self._loops)


__all__ = ["LoopCache", "MAX_CACHED_LOOPS"]
