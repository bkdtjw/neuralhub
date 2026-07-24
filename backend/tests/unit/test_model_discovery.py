"""模型探测：各 provider 类型的 URL/头/解析口径 + detect-models 路由的凭据回落。"""

from __future__ import annotations

import pytest

from backend.adapters import model_discovery
from backend.api.routes import providers as providers_route
from backend.common import LLMError
from backend.common.types import ProviderConfig
from backend.schemas.provider import DetectModelsRequest


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeClient:
    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        self.calls.append((url, dict(headers or {})))
        return self.routes.get(url, _FakeResponse(404, {}))


def _install(monkeypatch: pytest.MonkeyPatch, routes: dict[str, _FakeResponse]) -> _FakeClient:
    client = _FakeClient(routes)
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", lambda **_: client)
    return client


async def test_anthropic_hits_v1_models_with_dual_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"id": "claude-a"}, {"id": "claude-b"}, {"id": "claude-a"}]}
    client = _install(
        monkeypatch, {"https://gw.example.com/v1/models": _FakeResponse(200, payload)}
    )
    models = await model_discovery.discover_models("anthropic", "https://gw.example.com/", "sk-x")
    assert models == ["claude-a", "claude-b"]
    url, headers = client.calls[0]
    assert url == "https://gw.example.com/v1/models"
    assert headers["x-api-key"] == "sk-x"
    assert headers["authorization"] == "Bearer sk-x"
    assert headers["anthropic-version"] == "2023-06-01"


async def test_openai_base_with_v1_hits_models(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"object": "list", "data": [{"id": "gpt-a"}, {"id": "gpt-b"}]}
    client = _install(monkeypatch, {"https://api.example.com/v1/models": _FakeResponse(200, payload)})
    models = await model_discovery.discover_models("openai_compat", "https://api.example.com/v1", "sk-y")
    assert models == ["gpt-a", "gpt-b"]
    url, headers = client.calls[0]
    assert url == "https://api.example.com/v1/models"
    assert headers == {"authorization": "Bearer sk-y"}


async def test_ollama_parses_tags_with_default_base(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"models": [{"name": "llama3:latest"}, {"name": "qwen3"}]}
    client = _install(monkeypatch, {"http://localhost:11434/api/tags": _FakeResponse(200, payload)})
    models = await model_discovery.discover_models("ollama", "", "")
    assert models == ["llama3:latest", "qwen3"]
    assert client.calls[0][0] == "http://localhost:11434/api/tags"


async def test_falls_back_to_second_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"id": "claude-a"}]}
    client = _install(monkeypatch, {"https://gw.example.com/models": _FakeResponse(200, payload)})
    models = await model_discovery.discover_models("anthropic", "https://gw.example.com", "sk-x")
    assert models == ["claude-a"]
    assert [url for url, _ in client.calls] == [
        "https://gw.example.com/v1/models",
        "https://gw.example.com/models",
    ]


async def test_all_candidates_failing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {})
    with pytest.raises(LLMError) as exc_info:
        await model_discovery.discover_models("openai_compat", "https://api.example.com/v1", "sk")
    assert exc_info.value.code == "MODEL_DISCOVERY_ERROR"
    assert "HTTP 404" in exc_info.value.message


async def test_detect_models_route_falls_back_to_stored_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = ProviderConfig(
        id="p1",
        name="kimi",
        provider_type="anthropic",
        base_url="https://stored.example.com",
        api_key="sk-stored",
        default_model="kimi-k2",
    )
    seen: dict[str, str] = {}

    async def fake_list_all() -> list[ProviderConfig]:
        return [stored]

    async def fake_discover(provider_type: str, base_url: str, api_key: str) -> list[str]:
        seen.update(provider_type=provider_type, base_url=base_url, api_key=api_key)
        return ["kimi-k2", "kimi-k2-turbo"]

    monkeypatch.setattr(providers_route.provider_manager, "list_all", fake_list_all)
    monkeypatch.setattr(providers_route, "discover_models", fake_discover)
    response = await providers_route.detect_models(
        DetectModelsRequest(provider_type="anthropic_compat", provider_id="p1")
    )
    assert response.ok is True
    assert response.models == ["kimi-k2", "kimi-k2-turbo"]
    assert seen == {
        "provider_type": "anthropic",
        "base_url": "https://stored.example.com",
        "api_key": "sk-stored",
    }


async def test_detect_models_route_reports_failure_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(provider_type: str, base_url: str, api_key: str) -> list[str]:
        raise LLMError("MODEL_DISCOVERY_ERROR", "HTTP 401", provider_type)

    monkeypatch.setattr(providers_route, "discover_models", fake_discover)
    response = await providers_route.detect_models(
        DetectModelsRequest(provider_type="openai_compat", base_url="https://x.example/v1", api_key="bad")
    )
    assert response.ok is False
    assert response.models == []
    assert "HTTP 401" in response.message
