from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.api.routes import mcp as mcp_routes
from backend.common.types import MCPServerStatus
from backend.config.settings import settings
from backend.core.s05_skills import SpecRegistry


class FakeMCPManager:
    def __init__(self) -> None:
        self._statuses: list[MCPServerStatus] = []

    async def add_server(self, body: object) -> str:
        server_id = str(getattr(body, "id", "server"))
        self._statuses = [
            MCPServerStatus(
                id=server_id,
                name=str(getattr(body, "name", server_id)),
                transport=str(getattr(body, "transport", "stdio")),
                connected=False,
                tool_count=0,
                enabled=bool(getattr(body, "enabled", True)),
            )
        ]
        return server_id

    async def list_servers(self) -> list[MCPServerStatus]:
        return list(self._statuses)

    async def disconnect_all(self) -> None:
        self._statuses.clear()


@pytest.fixture(autouse=True)
def bind_test_database() -> Generator[None, None, None]:
    # 覆盖 conftest 的真库绑定：本模块鉴权测试全程不碰 DB（client fixture 已 no-op init_db，
    # 受保护路由在鉴权层即 401），跳过 PostgresContainer——既加速又消除 asyncpg 事件循环 teardown flake。
    yield


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    original_secret = settings.auth_secret
    settings.auth_secret = "test-secret"

    async def _noop_init_db() -> None:
        return None

    async def _noop_init_agent_runtime(**_kwargs: object) -> tuple[SpecRegistry, None]:
        return SpecRegistry(), None

    def _noop_init_task_queue(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("backend.api.app.init_db", _noop_init_db)
    monkeypatch.setattr("backend.api.app.init_agent_runtime", _noop_init_agent_runtime)
    monkeypatch.setattr("backend.api.app.init_task_queue", _noop_init_task_queue)
    monkeypatch.setattr(mcp_routes, "mcp_server_manager", FakeMCPManager())
    with TestClient(create_app()) as test_client:
        yield test_client
    settings.auth_secret = original_secret


def test_protected_routes_reject_missing_token(client: TestClient) -> None:
    valid_body = {
        "id": "valid-id_123",
        "name": "Demo",
        "transport": "stdio",
        "command": "npx",
        "args": [],
        "env": {},
        "enabled": True,
    }
    response = client.post("/api/mcp/servers", json=valid_body)
    assert response.status_code == 401
    assert response.json() == {
        "detail": {
            "code": "UNAUTHORIZED",
            "message": "Invalid or missing authentication token",
        }
    }


def test_protected_routes_reject_invalid_token(client: TestClient) -> None:
    response = client.post(
        "/api/mcp/servers",
        json={
            "id": "valid-id_123",
            "name": "Demo",
            "transport": "stdio",
            "command": "npx",
        },
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_protected_routes_accept_valid_token(client: TestClient) -> None:
    response = client.post(
        "/api/mcp/servers",
        json={
            "id": "valid-id_123",
            "name": "Demo",
            "transport": "stdio",
            "command": "npx",
            "args": [],
            "env": {},
            "enabled": True,
        },
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "valid-id_123"


@pytest.mark.parametrize(
    "path",
    ["/api/providers", "/api/sessions", "/api/metrics/summary", "/api/logs/search?trace_id=test"],
)
def test_provider_and_session_routes_require_auth(
    client: TestClient,
    path: str,
) -> None:
    response = client.get(path)
    assert response.status_code == 401


def test_health_route_does_not_require_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
