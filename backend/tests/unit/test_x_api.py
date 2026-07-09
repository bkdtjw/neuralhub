from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.routes import mcp as mcp_routes
from backend.api.x_search_service import XSearchQuery, XSearchResult
from backend.common.x_budget import XBudgetError
from backend.config.settings import settings
from backend.core.s02_tools.builtin.x_client import XClientConfig, XClientError, XPost
from backend.core.s05_skills import SpecRegistry

_AUTH = {"Authorization": "Bearer test-secret"}


class _FakeMCP:
    # 替换真 MCP 管理器：避免 lifespan 关停时去 DB 列 MCP 服务器（本模块不碰 DB）。
    async def list_servers(self) -> list[object]:
        return []

    async def disconnect_all(self) -> None:
        return None


@pytest.fixture(autouse=True)
def bind_test_database() -> Generator[None, None, None]:
    # 鉴权/路由测试不碰 DB（init_* 已 no-op），跳过 PostgresContainer 消除 teardown flake。
    yield


async def _noop_init_db() -> None:
    return None


async def _noop_init_runtime(**_kwargs: object) -> tuple[SpecRegistry, None]:
    return SpecRegistry(), None


def _noop_init_task_queue(*_args: object, **_kwargs: object) -> None:
    return None


def _prime(monkeypatch: pytest.MonkeyPatch, *, flag: bool) -> None:
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "x_api_enabled", flag)
    monkeypatch.setattr("backend.api.app.init_db", _noop_init_db)
    monkeypatch.setattr("backend.api.app.init_agent_runtime", _noop_init_runtime)
    monkeypatch.setattr("backend.api.app.init_task_queue", _noop_init_task_queue)
    monkeypatch.setattr(mcp_routes, "mcp_server_manager", _FakeMCP())


def _post() -> XPost:
    return XPost(
        author_name="Alice", author_handle="alice", text="claude is great",
        likes=12, retweets=3, replies=1, views=900,
        created_at="2026-01-01", url="https://x.com/alice/1",
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    _prime(monkeypatch, flag=True)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_search_returns_structured_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
        return XSearchResult(posts=[_post()], rate_limited=False, cached=False)

    monkeypatch.setattr("backend.api.routes.x_api.run_x_search", _fake)
    resp = client.get("/api/x/searches?q=claude&days=7&limit=3", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "claude" and body["count"] == 1
    assert body["results"][0]["author_handle"] == "alice"
    assert body["rate_limited"] is False


def test_missing_token_is_401(client: TestClient) -> None:
    assert client.get("/api/x/searches?q=claude").status_code == 401


def test_invalid_days_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
        return XSearchResult(posts=[])

    monkeypatch.setattr("backend.api.routes.x_api.run_x_search", _fake)
    assert client.get("/api/x/searches?q=claude&days=9999", headers=_AUTH).status_code == 422


def test_empty_query_is_422(client: TestClient) -> None:
    assert client.get("/api/x/searches?q=", headers=_AUTH).status_code == 422


def test_budget_exceeded_is_429_with_retry_after(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
        raise XBudgetError("今日额度已用尽", 3600)

    monkeypatch.setattr("backend.api.routes.x_api.run_x_search", _fake)
    resp = client.get("/api/x/searches?q=claude", headers=_AUTH)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "3600"
    assert resp.json()["detail"]["code"] == "X_BUDGET_EXCEEDED"


def test_upstream_error_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
        raise XClientError("X/Twitter 登录被 Cloudflare 拦截")

    monkeypatch.setattr("backend.api.routes.x_api.run_x_search", _fake)
    resp = client.get("/api/x/searches?q=claude", headers=_AUTH)
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "X_UPSTREAM_ERROR"


def test_route_absent_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _prime(monkeypatch, flag=False)  # 开关关闭 → 路由根本不注册
    with TestClient(create_app()) as test_client:
        resp = test_client.get("/api/x/searches?q=claude", headers=_AUTH)
        assert resp.status_code == 404
