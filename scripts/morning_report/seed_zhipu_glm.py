"""Seed Zhipu GLM-5V provider.

运行: ZHIPU_API_KEY=sk-... python -m scripts.morning_report.seed_zhipu_glm
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol

from backend.common.errors import AgentError
from backend.common.types import ProviderConfig, ProviderType

PROVIDER_ID = "zhipu-glm-5v"


class ProviderStoreLike(Protocol):
    async def get(self, provider_id: str) -> ProviderConfig | None: ...

    async def add(self, config: ProviderConfig) -> ProviderConfig: ...

    async def update(self, provider_id: str, **kwargs: object) -> ProviderConfig | None: ...


async def seed_zhipu_glm(api_key: str, store: ProviderStoreLike | None = None) -> str:
    if not api_key.strip():
        raise AgentError("ZHIPU_API_KEY_MISSING", "ZHIPU_API_KEY is required")
    resolved_store = store or _default_store()
    existing = await resolved_store.get(PROVIDER_ID)
    if existing is not None:
        await resolved_store.update(PROVIDER_ID, api_key=api_key.strip())
        return "updated"
    await resolved_store.add(
        ProviderConfig(
            id=PROVIDER_ID,
            name="Zhipu GLM-5V-Turbo",
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key=api_key.strip(),
            default_model="glm-5v-turbo",
            extra_body={"thinking": {"type": "enabled"}},
            roles="vision",
            enabled=True,
        )
    )
    return "created"


def _default_store() -> ProviderStoreLike:
    from backend.storage import ProviderStore

    return ProviderStore()


async def _main() -> None:
    try:
        status = await seed_zhipu_glm(os.environ.get("ZHIPU_API_KEY", ""))
        print(f"{PROVIDER_ID}: {status}")
    except AgentError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from exc


if __name__ == "__main__":
    asyncio.run(_main())
