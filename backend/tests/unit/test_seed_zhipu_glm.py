from __future__ import annotations

from scripts.morning_report.seed_zhipu_glm import PROVIDER_ID, seed_zhipu_glm

from backend.common.types import ProviderConfig, ProviderType


class FakeProviderStore:
    def __init__(self, existing: ProviderConfig | None = None) -> None:
        self.existing = existing
        self.added: ProviderConfig | None = None
        self.updated: tuple[str, dict[str, object]] | None = None

    async def get(self, provider_id: str) -> ProviderConfig | None:
        self.provider_id = provider_id
        return self.existing

    async def add(self, config: ProviderConfig) -> ProviderConfig:
        self.added = config
        return config

    async def update(self, provider_id: str, **kwargs: object) -> ProviderConfig | None:
        self.updated = (provider_id, kwargs)
        return self.existing


def _provider() -> ProviderConfig:
    return ProviderConfig(
        id=PROVIDER_ID,
        name="Zhipu",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="https://example.com",
        default_model="glm-5v-turbo",
    )


async def test_seed_zhipu_glm_inserts_provider() -> None:
    store = FakeProviderStore()

    status = await seed_zhipu_glm("sk-test", store)

    assert status == "created"
    assert store.added is not None
    assert store.added.id == PROVIDER_ID
    assert store.added.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert store.added.extra_body == {"thinking": {"type": "enabled"}}
    assert store.added.roles == "vision"


async def test_seed_zhipu_glm_updates_existing_api_key() -> None:
    store = FakeProviderStore(_provider())

    status = await seed_zhipu_glm("sk-new", store)

    assert status == "updated"
    assert store.updated == (PROVIDER_ID, {"api_key": "sk-new"})
    assert store.added is None
