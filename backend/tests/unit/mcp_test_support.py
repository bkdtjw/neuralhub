from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    MCPServerConfig,
    MCPToolInfo,
    StreamChunk,
)
from backend.core.s02_tools.mcp import MCPClient, MCPServerManager
from backend.storage import MCPServerStore

from .storage_test_support import make_test_session_factory


class FlakyMCPClient(MCPClient):
    def __init__(self, server_config: MCPServerConfig) -> None:
        self._server_config = server_config
        self._connected = False
        self.fail_list_tools = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def list_tools(self) -> list[MCPToolInfo]:
        if self.fail_list_tools:
            raise AgentError("MCP_LIST_TOOLS_ERROR", "list_tools returned 400")
        return [
            MCPToolInfo(
                name="echo",
                description="Echo",
                input_schema={"type": "object"},
                server_id=self._server_config.id,
            )
        ]


class BrokenDisconnectClient(FlakyMCPClient):
    async def disconnect(self) -> None:
        raise AgentError(
            "MCP_DISCONNECT_ERROR",
            "Attempted to exit cancel scope in a different task than it was entered in",
        )


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else LLMResponse(content="")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


async def make_flaky_manager(
    tmp_path: Path, client_cls: type[FlakyMCPClient] = FlakyMCPClient
) -> tuple[MCPServerManager, dict[str, FlakyMCPClient]]:
    _engine, session_factory = await make_test_session_factory(
        tmp_path, f"mcp_degradation_{uuid4().hex}"
    )
    created: dict[str, FlakyMCPClient] = {}

    def factory(config: MCPServerConfig) -> FlakyMCPClient:
        client = client_cls(config)
        created[config.id] = client
        return client

    manager = MCPServerManager(
        config_path=str(tmp_path / "empty_mcp.json"),
        client_factory=factory,
        store=MCPServerStore(session_factory),
    )
    return manager, created


def server_config(server_id: str) -> MCPServerConfig:
    return MCPServerConfig(
        id=server_id,
        name=server_id,
        transport="stdio",
        command="npx",
        args=["demo"],
        enabled=True,
    )
