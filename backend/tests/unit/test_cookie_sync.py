from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes.cookie_sync import router
from backend.config.settings import settings
from backend.storage.storage_state_store import (
    StorageStatePayload,
    StorageStateStore,
)


def test_storage_state_store_writes_playwright_state(tmp_path: Path) -> None:
    store = StorageStateStore(root=tmp_path)
    path = store.save(
        StorageStatePayload(
            user_id="u1",
            domain="example.com",
            cookies=[
                {
                    "name": "sid",
                    "value": "abc",
                    "domain": ".example.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "lax",
                }
            ],
            local_storage={"token": "local"},
        )
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cookies"][0]["httpOnly"] is True
    assert data["cookies"][0]["sameSite"] == "Lax"
    assert data["origins"][0]["origin"] == "https://example.com"
    assert store.is_state_fresh("u1", "example.com") is True


@pytest.mark.asyncio
async def test_cookie_sync_endpoint_saves_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings.auth_secret = "secret"
    monkeypatch.setenv("STORAGE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "backend.api.routes.cookie_sync.StorageStateStore",
        lambda: StorageStateStore(root=tmp_path),
    )
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/cookie/sync",
            json={
                "user_id": "u1",
                "domain": "example.com",
                "token": "secret",
                "cookies": [{"name": "sid", "value": "abc", "domain": ".example.com"}],
                "local_storage": {"theme": "dark"},
            },
        )
    assert response.status_code == 200
    path = Path(response.json()["path"])
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["origins"][0]["localStorage"] == [{"name": "theme", "value": "dark"}]
