from __future__ import annotations


class PendingMessageQueue:
    """运行中追加的用户消息队列（边跑边聊）。

    WS 层在 loop 忙时 push；run 循环在迭代边界 drain 后注入历史，
    模型最终应答前若有排队消息则继续对话而不是结束本轮。
    单事件循环内同步操作，无并发写冲突；不持久化。
    """

    def __init__(self) -> None:
        self._items: list[str] = []

    def push(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self._items.append(cleaned)

    def drain(self) -> list[str]:
        items = self._items
        self._items = []
        return items

    def __len__(self) -> int:
        return len(self._items)


__all__ = ["PendingMessageQueue"]
