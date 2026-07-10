from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.x_monitors import router
from backend.config.settings import settings
from backend.core.s05_skills import SpecRegistry

_AUTH = {"Authorization": "Bearer test-secret"}


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"query": "claude", "interval_minutes": 15, "threshold_likes": 100}
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_secret", "test-secret")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # 只挂本路由的最小 app + ASGITransport：与 DB fixture 同事件循环，避免 TestClient 跨循环用 asyncpg。
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_missing_token_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/x/monitors")).status_code == 401


@pytest.mark.asyncio
async def test_create_list_patch_delete_roundtrip(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/x/monitors", json=_body(), headers=_AUTH)
    assert created.status_code == 200
    monitor = created.json()
    assert monitor["query"] == "claude" and monitor["last_run_at"] is None

    listed = (await client.get("/api/x/monitors", headers=_AUTH)).json()["monitors"]
    assert any(item["id"] == monitor["id"] for item in listed)

    patched = await client.patch(
        f"/api/x/monitors/{monitor['id']}", json={"interval_minutes": 30}, headers=_AUTH
    )
    assert patched.status_code == 200 and patched.json()["interval_minutes"] == 30

    hits = await client.get(f"/api/x/monitors/{monitor['id']}/hits", headers=_AUTH)
    assert hits.status_code == 200 and hits.json()["hits"] == []

    deleted = await client.delete(f"/api/x/monitors/{monitor['id']}", headers=_AUTH)
    assert deleted.json() == {"deleted": True}
    assert (await client.get(f"/api/x/monitors/{monitor['id']}", headers=_AUTH)).status_code == 404


@pytest.mark.asyncio
async def test_interval_below_floor_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/x/monitors", json=_body(interval_minutes=5), headers=_AUTH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "X_MONITOR_INTERVAL_TOO_SMALL"


@pytest.mark.asyncio
async def test_all_zero_thresholds_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/x/monitors", json=_body(threshold_likes=0, threshold_views=0), headers=_AUTH
    )
    assert resp.status_code == 422  # Pydantic 校验：至少一个阈值 > 0


@pytest.mark.asyncio
async def test_monitor_count_cap_is_409(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "x_monitor_max_count", 1)
    first = await client.post("/api/x/monitors", json=_body(query="only-one"), headers=_AUTH)
    assert first.status_code == 200
    second = await client.post("/api/x/monitors", json=_body(query="overflow"), headers=_AUTH)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "X_MONITOR_LIMIT_REACHED"
    await client.delete(f"/api/x/monitors/{first.json()['id']}", headers=_AUTH)


# ---- 注册开关（不碰 DB，用完整 app + TestClient 验证路由是否挂载） ----


class _FakeMCP:
    async def list_servers(self) -> list[object]:
        return []

    async def disconnect_all(self) -> None:
        return None


def _prime_full_app(monkeypatch: pytest.MonkeyPatch, *, flag: bool) -> None:
    from backend.api.routes import mcp as mcp_routes

    async def _noop_init_db() -> None:
        return None

    async def _noop_init_runtime(**_kwargs: object) -> tuple[SpecRegistry, None]:
        return SpecRegistry(), None

    monkeypatch.setattr(settings, "x_monitor_enabled", flag)
    monkeypatch.setattr("backend.api.app.init_db", _noop_init_db)
    monkeypatch.setattr("backend.api.app.init_agent_runtime", _noop_init_runtime)
    monkeypatch.setattr("backend.api.app.init_task_queue", lambda *a, **k: None)
    monkeypatch.setattr(mcp_routes, "mcp_server_manager", _FakeMCP())
    # 注册测试不启动后台轮询器（其逻辑由 test_x_monitor_runner 单独覆盖）。
    monkeypatch.setattr("backend.api.x_monitor_runner.start_x_monitor_runner", lambda app: None)


class TestFlagRegistration:
    @pytest.fixture(autouse=True)
    def bind_test_database(self) -> Generator[None, None, None]:
        # 类级覆盖 conftest 的真库夹具：注册开关测试不碰 DB，避免 TestClient 跨循环拆 asyncpg。
        yield

    def test_routes_absent_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.api.app import create_app

        _prime_full_app(monkeypatch, flag=False)
        with TestClient(create_app()) as off_client:
            assert off_client.get("/api/x/monitors", headers=_AUTH).status_code == 404

    def test_routes_present_when_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 单测试单 app：同一测试连开两个 app 会在首个关闭时拆掉 fakeredis，第二个启动即超时。
        from backend.api.app import create_app

        _prime_full_app(monkeypatch, flag=True)
        with TestClient(create_app()) as on_client:
            # 挂载后鉴权立即生效；断言 401（非 404）即证明路由已注册，且不触库。
            assert on_client.get("/api/x/monitors").status_code == 401
