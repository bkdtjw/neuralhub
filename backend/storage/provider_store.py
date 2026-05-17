from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update

from backend.common.errors import AgentError
from backend.common.types import ProviderConfig

from .database import SessionFactory, get_db_session
from .models import ProviderRecord
from .provider_serializers import to_provider_config, to_provider_record
from .store_support import copy_fields

_PROVIDER_FIELDS = (
    "name",
    "provider_type",
    "base_url",
    "api_key",
    "default_model",
    "available_models_json",
    "extra_headers_json",
    "enable_prompt_cache",
    "prompt_cache_retention",
    "extra_body_json",
    "is_default",
    "enabled",
    "roles",
)


class ProviderStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def list_all(self) -> list[ProviderConfig]:
        try:
            async with get_db_session(self._session_factory) as db:
                rows = (
                    (await db.execute(select(ProviderRecord).order_by(ProviderRecord.id)))
                    .scalars()
                    .all()
                )
                return [to_provider_config(row) for row in rows]
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_LIST_ERROR", str(exc)) from exc

    async def get(self, provider_id: str) -> ProviderConfig | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(ProviderRecord, provider_id)
                return to_provider_config(row) if row is not None else None
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_GET_ERROR", str(exc)) from exc

    async def add(self, config: ProviderConfig) -> ProviderConfig:
        try:
            async with get_db_session(self._session_factory) as db:
                if await db.get(ProviderRecord, config.id) is not None:
                    raise AgentError("PROVIDER_EXISTS", f"Provider already exists: {config.id}")
                db.add(to_provider_record(config))
                await db.commit()
                return config
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_ADD_ERROR", str(exc)) from exc

    async def update(self, provider_id: str, **kwargs: Any) -> ProviderConfig | None:
        try:
            async with get_db_session(self._session_factory) as db:
                row = await db.get(ProviderRecord, provider_id)
                if row is None:
                    return None
                updated = to_provider_config(row).model_copy(update=kwargs)
                copy_fields(row, to_provider_record(updated), _PROVIDER_FIELDS)
                await db.commit()
                return updated
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_UPDATE_ERROR", str(exc)) from exc

    async def remove(self, provider_id: str) -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                result = await db.execute(
                    delete(ProviderRecord).where(ProviderRecord.id == provider_id)
                )
                await db.commit()
                return bool(result.rowcount)
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_REMOVE_ERROR", str(exc)) from exc

    async def set_default(self, provider_id: str) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                if await db.get(ProviderRecord, provider_id) is None:
                    raise AgentError("PROVIDER_NOT_FOUND", f"Provider not found: {provider_id}")
                await db.execute(update(ProviderRecord).values(is_default=False))
                await db.execute(
                    update(ProviderRecord)
                    .where(ProviderRecord.id == provider_id)
                    .values(is_default=True)
                )
                await db.commit()
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_SET_DEFAULT_ERROR", str(exc)) from exc

    async def import_from_json(self, configs: list[ProviderConfig]) -> int:
        try:
            async with get_db_session(self._session_factory) as db:
                count = 0
                existing = set((await db.execute(select(ProviderRecord.id))).scalars())
                for config in configs:
                    if config.id in existing:
                        continue
                    db.add(to_provider_record(config))
                    count += 1
                await db.commit()
                return count
        except Exception as exc:
            raise AgentError("PROVIDER_STORE_IMPORT_ERROR", str(exc)) from exc


__all__ = ["ProviderStore"]
