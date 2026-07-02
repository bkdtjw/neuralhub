from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from backend.api.middleware.auth import verify_token
from backend.api.routes import hooks
from backend.core.s07_task_system import event_hooks as eh
from backend.core.s07_task_system.event_hooks import HookStore
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


@pytest.fixture
async def client(tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with _client(tmp_path, with_runtime=True) as http_client:
        yield http_client


@pytest.fixture
async def client_without_runtime(tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with _client(tmp_path, with_runtime=False) as http_client:
        yield http_client


def _client(tmp_path: Path, *, with_runtime: bool) -> httpx.AsyncClient:
    async def _verify_token_override() -> None:
        return None

    app = FastAPI()
    app.state.hook_store = HookStore(path=str(tmp_path / "event_hooks.json"))
    calls: list[str] = []
    if with_runtime:
        app.state.hook_runtime = _runtime(calls)
    app.dependency_overrides[verify_token] = _verify_token_override
    app.include_router(hooks.router)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.event_hook_calls = calls  # type: ignore[attr-defined]
    return client


def _draft(name: str = "Prediction Market", accounts: list[str] | None = None) -> dict[str, object]:
    return {
        "name": name,
        "twitter": {
            "accounts": accounts or ["@Polymarket"],
            "keywords": ["election", "odds"],
        },
        "sources": {
            "exa_web": True,
            "zhipu_search": True,
            "youtube": False,
        },
        "cadence_minutes": 45,
        "materiality": 60,
        "enabled": True,
    }


def _runtime(calls: list[str]) -> HookRuntime:
    async def twitter_search_fn(query: eh.TwitterQuery) -> list[SimpleNamespace]:
        calls.append(f"search:{query.query}")
        return [
            SimpleNamespace(
                author_name="Reporter",
                author_handle="polymarket",
                text="Election odds moved sharply",
                likes=50,
                retweets=10,
                created_at="2026-06-27T00:00:00Z",
                url="https://x.com/polymarket/status/1",
            )
        ]

    async def assess_fn(request: eh.AssessRequest) -> eh.Assessment:
        calls.append(f"assess:{request.hook.id}")
        return eh.Assessment(
            materiality=90,
            summary="Confirmed",
            developments=[
                eh.Development(
                    text="Election odds moved sharply",
                    ts="2026-06-27T00:00:00Z",
                    source="twitter",
                )
            ],
        )

    async def push_fn(hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        calls.append(f"push:{hook.id}:{verdict.decision}")

    async def exa_search_fn(query: eh.ExaQuery) -> list[SimpleNamespace]:
        calls.append(f"exa:{query.query}")
        return []

    return HookRuntime(
        twitter_search_fn=twitter_search_fn,
        assess_fn=assess_fn,
        push_fn=push_fn,
        exa_search_fn=exa_search_fn,
    )


async def test_hooks_crud_log_and_run(client: httpx.AsyncClient) -> None:
    created_response = await client.post("/api/hooks", json=_draft())

    assert created_response.status_code == 200
    created = created_response.json()
    hook_id = created["hook"]["id"]
    created_at = created["hook"]["created_at"]
    assert hook_id
    assert created["hook"]["twitter"]["accounts"] == ["polymarket"]
    assert created["state"]["summary"] == "尚未扫描"

    list_response = await client.get("/api/hooks")
    assert list_response.status_code == 200
    assert [item["hook"]["id"] for item in list_response.json()["hooks"]] == [hook_id]

    get_response = await client.get(f"/api/hooks/{hook_id}")
    assert get_response.status_code == 200
    assert get_response.json()["hook"]["id"] == hook_id

    update_response = await client.put(f"/api/hooks/{hook_id}", json=_draft(name="Updated Hook"))
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["hook"]["name"] == "Updated Hook"
    assert updated["hook"]["created_at"] == created_at

    run_response = await client.post(f"/api/hooks/{hook_id}/run")
    assert run_response.status_code == 200
    assert run_response.json() == {"ok": True}
    calls = getattr(client, "event_hook_calls")
    assert "exa:election odds" in calls
    assert f"assess:{hook_id}" in calls
    assert f"push:{hook_id}:push" in calls

    log_response = await client.get(f"/api/hooks/{hook_id}/log")
    assert log_response.status_code == 200
    assert isinstance(log_response.json()["entries"], list)

    delete_response = await client.delete(f"/api/hooks/{hook_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}
    assert (await client.get(f"/api/hooks/{hook_id}")).status_code == 404


async def test_get_missing_hook_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/hooks/missing")

    assert response.status_code == 404


async def test_seen_marks_timeline_read(client: httpx.AsyncClient) -> None:
    # 缺陷 C：POST /seen 清 unseen_count，404 语义同其它接口。
    created = await client.post("/api/hooks", json=_draft())
    hook_id = created.json()["hook"]["id"]
    await client.post(f"/api/hooks/{hook_id}/run")  # 产生 timeline + unseen

    seen = await client.post(f"/api/hooks/{hook_id}/seen")
    assert seen.status_code == 200
    assert seen.json() == {"ok": True}
    state = (await client.get(f"/api/hooks/{hook_id}")).json()["state"]
    assert state["unseen_count"] == 0

    assert (await client.post("/api/hooks/missing/seen")).status_code == 404


async def test_revive_restores_developing_and_pending(client: httpx.AsyncClient) -> None:
    # 缺陷 B：POST /revive 复活钩子（developing + 立即 due），404 语义同其它接口。
    created = await client.post("/api/hooks", json=_draft())
    hook_id = created.json()["hook"]["id"]

    revive = await client.post(f"/api/hooks/{hook_id}/revive")
    assert revive.status_code == 200
    assert revive.json() == {"ok": True}
    state = (await client.get(f"/api/hooks/{hook_id}")).json()["state"]
    assert state["status"] == "developing"
    assert state["last_scanned"] == ""

    assert (await client.post("/api/hooks/missing/revive")).status_code == 404


async def test_post_normalizes_accounts(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/hooks", json=_draft(accounts=["@Polymarket"]))

    assert response.status_code == 200
    assert response.json()["hook"]["twitter"]["accounts"] == ["polymarket"]


async def test_run_without_runtime_returns_503(
    client_without_runtime: httpx.AsyncClient,
) -> None:
    created_response = await client_without_runtime.post("/api/hooks", json=_draft())
    hook_id = created_response.json()["hook"]["id"]

    response = await client_without_runtime.post(f"/api/hooks/{hook_id}/run")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "HOOK_RUNTIME_UNAVAILABLE"
