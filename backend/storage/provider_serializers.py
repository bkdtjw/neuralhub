from __future__ import annotations

import json

from backend.common.types import ProviderConfig
from backend.storage.models import ProviderRecord


def _dump_json(payload: list[object] | dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _load_list(payload: str) -> list[object]:
    loaded = json.loads(payload) if payload else []
    return loaded if isinstance(loaded, list) else []


def _load_dict(payload: str) -> dict[str, object]:
    loaded = json.loads(payload) if payload else {}
    return loaded if isinstance(loaded, dict) else {}


def to_provider_record(config: ProviderConfig) -> ProviderRecord:
    return ProviderRecord(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type.value,
        base_url=config.base_url,
        api_key=config.api_key,
        default_model=config.default_model,
        available_models_json=_dump_json(config.available_models),
        extra_headers_json=_dump_json(config.extra_headers),
        enable_prompt_cache=config.enable_prompt_cache,
        prompt_cache_retention=config.prompt_cache_retention,
        extra_body_json=_dump_json(config.extra_body),
        is_default=config.is_default,
        enabled=config.enabled,
        roles=config.roles,
    )


def to_provider_config(record: ProviderRecord) -> ProviderConfig:
    return ProviderConfig(
        id=record.id,
        name=record.name,
        provider_type=record.provider_type,
        base_url=record.base_url,
        api_key=record.api_key,
        default_model=record.default_model,
        available_models=[str(item) for item in _load_list(record.available_models_json)],
        extra_headers={
            str(key): str(value) for key, value in _load_dict(record.extra_headers_json).items()
        },
        enable_prompt_cache=record.enable_prompt_cache,
        prompt_cache_retention=record.prompt_cache_retention,
        extra_body=_load_dict(record.extra_body_json),
        is_default=record.is_default,
        enabled=record.enabled,
        roles=record.roles,
    )


__all__ = ["to_provider_config", "to_provider_record"]
