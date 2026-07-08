from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.common import LLMError
from backend.common.logging import get_logger
from backend.common.types import ProviderConfig
from backend.storage import ProviderStore

from .base import LLMAdapter
from .provider_manager_support import get_base_adapter, load_json_seed, normalize_defaults, normalize_provider_type, set_default_locked
from .provider_routing import ProviderRoutingContext, get_resilient_adapter
from .provider_seed_loader import DEFAULT_PROVIDER_SEED_PATH

logger = get_logger(component="provider_manager")


class ProviderManager:
    def __init__(self, config_path: str | None = None, store: ProviderStore | None = None) -> None:
        self._seed_path = Path(config_path) if config_path else DEFAULT_PROVIDER_SEED_PATH
        self._store = store or ProviderStore()
        self._aliases = {"openai": "openai_compat", "openai_compatible": "openai_compat", "claude_compat": "anthropic", "anthropic_compat": "anthropic"}
        # 进程内缓存：DB(ProviderStore) 是权威，但此缓存【不跨 gunicorn worker 失效】。
        # 多 worker 下一个 worker 改配置后其它 worker 仍读旧值——故默认单 worker（见 gunicorn_conf.py）。
        # 若要支持多 worker，需在写入(add/update/remove/set_default)处经 Redis pub/sub 广播失效、各 worker 重置 _initialized。
        self._providers: dict[str, ProviderConfig] = {}
        self._adapters: dict[str, LLMAdapter] = {}
        self._routed_adapters: dict[str, LLMAdapter] = {}
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        try:
            if self._initialized:
                return
            async with self._init_lock:
                if self._initialized:
                    return
                configs = await self._store.list_all()
                if not configs:
                    seeds = load_json_seed(self._seed_path, self._aliases)
                    if seeds:
                        await self._store.import_from_json(seeds)
                        configs = seeds
                self._providers = normalize_defaults({item.id: item for item in configs})
                default = next((item for item in self._providers.values() if item.is_default), None)
                if default is not None:
                    await self._store.set_default(default.id)
                    for item_id, config in list(self._providers.items()):
                        self._providers[item_id] = config.model_copy(update={"is_default": item_id == default.id})
                self._initialized = True
                logger.info("provider_manager_initialized", provider_count=len(self._providers))
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_INIT_ERROR", str(exc), "provider_manager") from exc

    async def add(self, config: ProviderConfig) -> ProviderConfig:
        try:
            await self._ensure_initialized()
            async with self._write_lock:
                if config.id in self._providers:
                    raise LLMError("PROVIDER_EXISTS", f"Provider already exists: {config.id}", "provider_manager")
                stored = await self._store.add(config)
                self._providers[stored.id] = stored
                if stored.is_default or not any(item.is_default for item in self._providers.values()):
                    await self._set_default_locked(stored.id)
                logger.info("provider_added", provider_id=stored.id, provider_type=stored.provider_type.value)
                return self._providers[stored.id]
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_ADD_ERROR", str(exc), "provider_manager") from exc

    async def update(self, provider_id: str, **kwargs: Any) -> ProviderConfig:
        try:
            await self._ensure_initialized()
            async with self._write_lock:
                current = self._providers.get(provider_id)
                if current is None:
                    raise LLMError("PROVIDER_NOT_FOUND", f"Provider not found: {provider_id}", "provider_manager")
                kwargs.pop("id", None)
                if "provider_type" in kwargs:
                    kwargs["provider_type"] = normalize_provider_type(
                        kwargs["provider_type"],
                        self._aliases,
                    )
                updated = await self._store.update(provider_id, **kwargs)
                if updated is None:
                    raise LLMError("PROVIDER_NOT_FOUND", f"Provider not found: {provider_id}", "provider_manager")
                self._providers[provider_id] = updated
                self._adapters.pop(provider_id, None)
                self._routed_adapters.clear()
                if updated.is_default or not any(item.is_default for item in self._providers.values()):
                    await self._set_default_locked(provider_id)
                logger.info("provider_updated", provider_id=provider_id)
                return self._providers[provider_id]
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_UPDATE_ERROR", str(exc), "provider_manager") from exc

    async def remove(self, provider_id: str) -> bool:
        try:
            await self._ensure_initialized()
            async with self._write_lock:
                removed = self._providers.pop(provider_id, None)
                self._adapters.pop(provider_id, None)
                self._routed_adapters.clear()
                if removed is None:
                    return False
                await self._store.remove(provider_id)
                if removed.is_default and self._providers:
                    await self._set_default_locked(next(iter(self._providers)))
                logger.info("provider_removed", provider_id=provider_id)
                return True
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_REMOVE_ERROR", str(exc), "provider_manager") from exc

    async def list_all(self) -> list[ProviderConfig]:
        try:
            await self._ensure_initialized()
            return list(self._providers.values())
        except Exception as exc:
            raise LLMError("PROVIDER_LIST_ERROR", str(exc), "provider_manager") from exc

    async def get_default(self) -> ProviderConfig | None:
        try:
            await self._ensure_initialized()
            return next((item for item in self._providers.values() if item.is_default), None)
        except Exception as exc:
            raise LLMError("PROVIDER_DEFAULT_ERROR", str(exc), "provider_manager") from exc

    async def set_default(self, provider_id: str) -> None:
        try:
            await self._ensure_initialized()
            async with self._write_lock:
                await self._set_default_locked(provider_id)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_SET_DEFAULT_ERROR", str(exc), "provider_manager") from exc

    async def test_connection(self, provider_id: str) -> bool:
        try:
            success = await (await self.get_adapter(provider_id)).test_connection()
            logger.info("provider_test", provider_id=provider_id, success=success)
            return success
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_TEST_ERROR", str(exc), "provider_manager") from exc

    async def get_adapter(self, provider_id: str | None = None) -> LLMAdapter:
        try:
            await self._ensure_initialized()
            default = await self.get_default() if self._providers else None
            target_id = provider_id or (default.id if default is not None else None)
            if target_id is None:
                raise LLMError("DEFAULT_PROVIDER_MISSING", "Default provider is not configured", "provider_manager")
            config = self._providers.get(target_id)
            if config is None:
                raise LLMError("PROVIDER_NOT_FOUND", f"Provider not found: {target_id}", "provider_manager")
            base_adapter = lambda item: get_base_adapter(item, self._adapters)
            routed = get_resilient_adapter(
                ProviderRoutingContext(config, self._providers, base_adapter, self._routed_adapters)
            )
            if routed is not None:
                return routed
            return base_adapter(config)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_ADAPTER_ERROR", str(exc), "provider_manager") from exc

    async def _set_default_locked(self, provider_id: str) -> None:
        try:
            await set_default_locked(
                provider_id,
                self._store,
                self._providers,
                self._adapters,
                self._routed_adapters,
            )
            logger.info("provider_default_set", provider_id=provider_id)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("PROVIDER_SET_DEFAULT_ERROR", str(exc), "provider_manager") from exc


__all__ = ["ProviderManager"]
