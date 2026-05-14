from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.role_router import RoleRouter
from backend.api.routes import provider_roles
from backend.common.types import ProviderConfig, ProviderType
from backend.config.settings import settings


@dataclass
class FakeSettings:
    main_agent_provider_id: str = ""
    vision_subagent_provider_id: str = ""


class FakeProviderManager:
    def __init__(self) -> None:
        self.providers = [
            _provider("text-a", roles="text"),
            _provider("vision-a", roles="vision"),
            _provider("vision-b", roles=""),
        ]

    async def list_all(self) -> list[ProviderConfig]:
        return list(self.providers)

    async def update(self, provider_id: str, **kwargs: object) -> ProviderConfig:
        for index, provider in enumerate(self.providers):
            if provider.id == provider_id:
                updated = provider.model_copy(update=kwargs)
                self.providers[index] = updated
                return updated
        raise AssertionError(f"unknown provider {provider_id}")


def _provider(provider_id: str, roles: str = "", enabled: bool = True) -> ProviderConfig:
    return ProviderConfig(
        id=provider_id,
        name=provider_id,
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="https://example.com",
        default_model="model",
        roles=roles,
        enabled=enabled,
    )


@pytest.mark.asyncio
async def test_role_router_uses_settings_default() -> None:
    manager = FakeProviderManager()
    router = RoleRouter(manager, FakeSettings(vision_subagent_provider_id="vision-b"))

    provider = await router.resolve_provider("vision")

    assert provider.id == "vision-b"


@pytest.mark.asyncio
async def test_role_router_uses_db_role_when_settings_empty() -> None:
    manager = FakeProviderManager()
    router = RoleRouter(manager, FakeSettings())

    provider = await router.resolve_provider("vision")

    assert provider.id == "vision-a"


@pytest.mark.asyncio
async def test_role_router_uses_override_id() -> None:
    manager = FakeProviderManager()
    router = RoleRouter(manager, FakeSettings(vision_subagent_provider_id="vision-a"))

    provider = await router.resolve_provider("vision", override_id="vision-b")

    assert provider.id == "vision-b"


def test_provider_role_patch_sets_db_default(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FakeProviderManager()
    app = FastAPI()
    app.include_router(provider_roles.router)
    original_secret = settings.auth_secret
    settings.auth_secret = "test-secret"
    monkeypatch.setattr(provider_roles, "provider_manager", manager)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/providers/role/vision",
                json={"provider_id": "vision-b"},
                headers={"Authorization": "Bearer test-secret"},
            )
    finally:
        settings.auth_secret = original_secret

    assert response.status_code == 200
    assert response.json() == {"role": "vision", "provider_id": "vision-b"}
    roles = {provider.id: provider.roles for provider in manager.providers}
    assert roles["vision-a"] == ""
    assert roles["vision-b"] == "vision"
