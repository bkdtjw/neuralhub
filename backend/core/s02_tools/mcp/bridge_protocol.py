from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BridgeProtocol(Protocol):
    def needs_sync(self) -> bool: ...

    async def sync_if_needed(self) -> int: ...

    async def sync_all(self) -> int: ...


__all__ = ["BridgeProtocol"]
