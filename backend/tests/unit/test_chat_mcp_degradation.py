from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.common.types import LLMResponse

from .mcp_test_support import MockAdapter, make_flaky_manager, server_config


@pytest.mark.asyncio
async def test_chat_completions_succeeds_with_failing_mcp_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api.routes import chat_completions as chat_module

    manager, created = await make_flaky_manager(tmp_path)
    await manager.add_server(server_config("healthy"))
    await manager.add_server(server_config("flaky"))
    created["flaky"].fail_list_tools = True
    adapter = MockAdapter([LLMResponse(content="OK")])

    async def fake_get_adapter(provider_id: str | None = None) -> MockAdapter:
        return adapter

    monkeypatch.setattr(chat_module, "mcp_server_manager", manager)
    monkeypatch.setattr(chat_module.provider_manager, "get_adapter", fake_get_adapter)

    app = FastAPI()
    app.include_router(chat_module.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "workspace": str(tmp_path),
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "OK"
    tool_names = {tool.name for request in adapter.requests for tool in request.tools or []}
    assert "mcp__healthy__echo" in tool_names
    assert not any(name.startswith("mcp__flaky__") for name in tool_names)
