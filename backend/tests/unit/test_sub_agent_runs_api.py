"""子 agent 转录查询路由：鉴权、run/agent 查询与 404。"""
from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from backend.api.routes import sub_agents as sub_agents_routes
from backend.config.settings import settings
from backend.core.s04_sub_agents import SubAgentTranscriptStore

AUTH = {"Authorization": "Bearer test-secret"}
FULL_OUTPUT = "完整输出-" + "z" * 400


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # Pure in-memory route tests: override conftest DB bind, skip PostgresContainer.
    yield


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    original_secret = settings.auth_secret
    settings.auth_secret = "test-secret"
    store = SubAgentTranscriptStore()
    store.record_spawned("run1", "orchestrate", ["researcher", "writer"], message="编排启动")
    store.record_entry("run1", "orchestrate", "researcher", "tool_result", FULL_OUTPUT, stage=1)
    store.record_done("run1", "orchestrate", "researcher", stage=1)
    monkeypatch.setattr(sub_agents_routes, "get_sub_agent_transcript_store", lambda: store)

    app = FastAPI()
    app.include_router(sub_agents_routes.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    settings.auth_secret = original_secret


@pytest.mark.asyncio
async def test_routes_require_auth(client: httpx.AsyncClient) -> None:
    for path in ("/api/sub-agent-runs", "/api/sub-agent-runs/run1", "/api/sub-agent-runs/run1/agents/researcher"):
        response = await client.get(path)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_runs(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/sub-agent-runs", headers=AUTH)
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run1"
    assert runs[0]["roles"] == ["researcher", "writer"]


@pytest.mark.asyncio
async def test_get_run_and_agent_full_content(client: httpx.AsyncClient) -> None:
    run_response = await client.get("/api/sub-agent-runs/run1", headers=AUTH)
    assert run_response.status_code == 200
    body = run_response.json()
    assert body["order"] == ["researcher", "writer"]
    assert body["agents"]["researcher"]["status"] == "done"

    agent_response = await client.get("/api/sub-agent-runs/run1/agents/researcher", headers=AUTH)
    assert agent_response.status_code == 200
    agent = agent_response.json()
    assert agent["stage"] == 1
    assert agent["entries"][0]["content"] == FULL_OUTPUT  # 全文透出，非 160 字符预览


@pytest.mark.asyncio
async def test_unknown_run_or_agent_returns_404(client: httpx.AsyncClient) -> None:
    missing_run = await client.get("/api/sub-agent-runs/nope", headers=AUTH)
    assert missing_run.status_code == 404
    assert missing_run.json()["detail"]["code"] == "SUB_AGENT_RUN_NOT_FOUND"

    missing_agent = await client.get("/api/sub-agent-runs/run1/agents/nope", headers=AUTH)
    assert missing_agent.status_code == 404
    assert missing_agent.json()["detail"]["code"] == "SUB_AGENT_NOT_FOUND"
