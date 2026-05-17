from __future__ import annotations

from backend.core.s02_tools.mcp import BridgeProtocol


class DummyBridge:
    def needs_sync(self) -> bool:
        return False

    async def sync_if_needed(self) -> int:
        return -1

    async def sync_all(self) -> int:
        return 0


def test_bridge_protocol_accepts_structural_implementation() -> None:
    assert isinstance(DummyBridge(), BridgeProtocol)
