from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import httpx
import pytest

from backend.tests.unit.module_reload_support import fresh_import


class FakeTranscriptError(Exception):
    """字幕获取失败。"""


class FakeIpBlocked(FakeTranscriptError):
    """模拟 YouTube transcript API 的 IpBlocked。"""


class FakeProxyConfig:
    def __init__(self, http_url: str | None = None, https_url: str | None = None) -> None:
        self.http_url = http_url
        self.https_url = https_url


class FakeSnippet:
    def __init__(self, text: str, start: float, duration: float) -> None:
        self.text = text
        self.start = start
        self.duration = duration


class FakeTranscriptApi:
    responses: dict[tuple[str, tuple[str, ...] | None], Any] = {}
    instances: list["FakeTranscriptApi"] = []

    def __init__(self, proxy_config: FakeProxyConfig | None = None, http_client: Any = None) -> None:
        self.proxy_config = proxy_config
        self.http_client = http_client
        self.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.responses = {}
        cls.instances = []

    @classmethod
    def get_transcript(
        cls,
        video_id: str,
        languages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return cls._resolve(video_id, tuple(languages) if languages else None)

    def fetch(
        self,
        video_id: str,
        languages: tuple[str, ...] | list[str] = ("en",),
        preserve_formatting: bool = False,
    ) -> Any:
        del preserve_formatting
        normalized_languages = tuple(languages) if languages else None
        return self._resolve(video_id, normalized_languages)

    @classmethod
    def _resolve(cls, video_id: str, languages: tuple[str, ...] | None) -> Any:
        response = cls.responses.get((video_id, languages), [])
        if isinstance(response, Exception):
            raise response
        return response


class FakeHttpResponse:
    def __init__(self, status_code: int, data: dict[str, Any], url: str) -> None:
        self.status_code = status_code
        self._data = data
        self._request = httpx.Request("GET", url)
        self._response = httpx.Response(status_code, request=self._request)

    def json(self) -> dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self._request, response=self._response)


class FakeHttpClient:
    def __init__(self, responses: dict[str, FakeHttpResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []
        self.init_kwargs: dict[str, Any] = {}

    async def __aenter__(self) -> "FakeHttpClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        self.calls.append({"url": url, **kwargs})
        for key, response in self._responses.items():
            if key in url:
                return response
        return FakeHttpResponse(404, {}, url)


def install_transcript_module(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTranscriptApi.reset()
    module = ModuleType("youtube_transcript_api")
    proxies = ModuleType("youtube_transcript_api.proxies")
    proxies.GenericProxyConfig = FakeProxyConfig
    module.YouTubeTranscriptApi = FakeTranscriptApi
    module.TranscriptsDisabled = FakeTranscriptError
    module.NoTranscriptFound = FakeTranscriptError
    module.CouldNotRetrieveTranscript = FakeTranscriptError
    module.RequestBlocked = FakeTranscriptError
    module.IpBlocked = FakeIpBlocked
    module.proxies = proxies
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", module)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api.proxies", proxies)


def load_modules(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    install_transcript_module(monkeypatch)
    # 经 fresh_import 重导：测试结束后 sys.modules 还原为原模块，避免重导出的
    # 新异常类泄漏给后续用例（详见 module_reload_support）。
    _, youtube_client, youtube_search = fresh_import(
        monkeypatch,
        "backend.core.s02_tools.builtin.youtube_transcript_client",
        "backend.core.s02_tools.builtin.youtube_client",
        "backend.core.s02_tools.builtin.youtube_search",
    )
    return youtube_client, youtube_search


def install_http_client(
    monkeypatch: pytest.MonkeyPatch,
    youtube_client: Any,
    responses: dict[str, FakeHttpResponse],
) -> FakeHttpClient:
    client = FakeHttpClient(responses)
    monkeypatch.setattr(
        youtube_client.httpx,
        "AsyncClient",
        lambda **kwargs: _install_client_with_kwargs(client, kwargs),
    )
    return client


def _install_client_with_kwargs(client: FakeHttpClient, kwargs: dict[str, Any]) -> FakeHttpClient:
    client.init_kwargs = kwargs
    return client


__all__ = [
    "FakeHttpClient",
    "FakeHttpResponse",
    "FakeIpBlocked",
    "FakeProxyConfig",
    "FakeSnippet",
    "FakeTranscriptApi",
    "FakeTranscriptError",
    "install_http_client",
    "load_modules",
]
