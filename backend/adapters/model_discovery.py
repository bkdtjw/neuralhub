from __future__ import annotations

import httpx

from backend.common import LLMError
from backend.config.http_client import load_http_client_config

_TIMEOUT_SECONDS = 15.0
_OLLAMA_DEFAULT_BASE = "http://localhost:11434"


def _candidate_urls(provider_type: str, base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    if provider_type == "ollama":
        root = base or _OLLAMA_DEFAULT_BASE
        for suffix in ("/api/chat", "/api"):
            root = root.removesuffix(suffix)
        return [f"{root}/api/tags"]
    if base.endswith("/v1"):
        return [f"{base}/models"]
    if provider_type == "anthropic":
        # anthropic 适配器的 base 不含 /v1（chat 打 {base}/v1/messages），models 同理优先 /v1/models
        return [f"{base}/v1/models", f"{base}/models"]
    # openai_compat 的 chat 打 {base}/chat/completions，models 对应 {base}/models；/v1/models 兜底
    return [f"{base}/models", f"{base}/v1/models"]


def _headers(provider_type: str, api_key: str) -> dict[str, str]:
    if provider_type == "anthropic":
        headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            # 兼容网关鉴权口径不一：官方认 x-api-key，new-api/sub2api 一类常认 Bearer，双发无害
            headers["x-api-key"] = api_key
            headers["authorization"] = f"Bearer {api_key}"
        return headers
    if api_key:
        return {"authorization": f"Bearer {api_key}"}
    return {}


def _parse_models(data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    items = data.get("data") or data.get("models") or []
    names: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        elif isinstance(item, str) and item:
            names.append(item)
    seen: set[str] = set()
    return [name for name in names if not (name in seen or seen.add(name))]


async def discover_models(provider_type: str, base_url: str, api_key: str) -> list[str]:
    """探测上游可调用的模型列表（openai:/models、anthropic:/v1/models、ollama:/api/tags）。"""
    if provider_type != "ollama" and not base_url.strip():
        raise LLMError("MODEL_DISCOVERY_ERROR", "base_url is required", provider_type)
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, trust_env=load_http_client_config().trust_env
        ) as client:
            for url in _candidate_urls(provider_type, base_url.strip()):
                try:
                    response = await client.get(url, headers=_headers(provider_type, api_key))
                except httpx.HTTPError as exc:
                    errors.append(f"{url}: {exc}")
                    continue
                if response.status_code >= 400:
                    errors.append(f"{url}: HTTP {response.status_code}")
                    continue
                try:
                    models = _parse_models(response.json())
                except ValueError:
                    errors.append(f"{url}: invalid JSON")
                    continue
                if models:
                    return models
                errors.append(f"{url}: empty model list")
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError("MODEL_DISCOVERY_ERROR", str(exc), provider_type) from exc
    raise LLMError("MODEL_DISCOVERY_ERROR", "; ".join(errors) or "no models found", provider_type)


__all__ = ["discover_models"]
