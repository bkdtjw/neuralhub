from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from backend.tests.unit.module_reload_support import fresh_import


class FakeTooManyRequestsError(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__("rate limited")


class FakeUser:
    def __init__(self, name: str = "Test User", screen_name: str = "testuser") -> None:
        self.name = name
        self.screen_name = screen_name


class FakeTweet:
    def __init__(
        self,
        id: str = "123456",
        text: str = "Test tweet about Claude Code",
        user: FakeUser | None = None,
        favorite_count: int | None = 150,
        retweet_count: int | None = 30,
        reply_count: int | None = 5,
        view_count: int | None = 8000,
        created_at: str | None = "Tue Mar 25 10:30:00 +0000 2026",
    ) -> None:
        self.id = id
        self.text = text
        self.user = user
        self.favorite_count = favorite_count
        self.retweet_count = retweet_count
        self.reply_count = reply_count
        self.view_count = view_count
        self.created_at = created_at
        self.media = []


class FakeResult:
    def __init__(
        self,
        tweets: list[FakeTweet],
        next_result: FakeResult | None = None,
        next_exception: Exception | None = None,
    ) -> None:
        self._tweets = tweets
        self._next_result = next_result
        self._next_exception = next_exception

    def __iter__(self):
        return iter(self._tweets)

    def __len__(self) -> int:
        return len(self._tweets)

    async def next(self) -> FakeResult | None:
        if self._next_exception is not None:
            raise self._next_exception
        next_result = self._next_result
        self._next_result = None
        return next_result


class FakeClient:
    init_args: list[tuple[str | None, str | None]] = []
    login_calls: list[dict[str, Any]] = []
    search_calls: list[tuple[str, str, int]] = []
    login_exception: Exception | None = None
    search_response: Any = FakeResult([])

    def __init__(self, language: str | None = None, proxy: str | None = None) -> None:
        self.language = language
        self.proxy = proxy
        self.init_args.append((language, proxy))

    @classmethod
    def reset(cls) -> None:
        cls.init_args = []
        cls.login_calls = []
        cls.search_calls = []
        cls.login_exception = None
        cls.search_response = FakeResult([])

    async def login(self, **kwargs: Any) -> dict[str, object]:
        self.login_calls.append(kwargs)
        if self.login_exception is not None:
            raise self.login_exception
        return {}

    async def search_tweet(self, query: str, product: str, count: int = 20) -> Any:
        self.search_calls.append((query, product, count))
        if isinstance(self.search_response, Exception):
            raise self.search_response
        return self.search_response


def install_twikit_module(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.reset()
    module = ModuleType("twikit")
    module.Client = FakeClient
    module.TooManyRequests = FakeTooManyRequestsError
    monkeypatch.setitem(sys.modules, "twikit", module)


FakeTooManyRequests = FakeTooManyRequestsError


def load_modules(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    install_twikit_module(monkeypatch)
    # 经 fresh_import 重导：测试结束后 sys.modules 还原为原模块，避免新旧
    # XClientError 类身份分裂泄漏到后续用例（详见 module_reload_support）。
    x_client, x_search = fresh_import(
        monkeypatch,
        "backend.core.s02_tools.builtin.x_client",
        "backend.core.s02_tools.builtin.x_search",
    )
    return x_client, x_search


__all__ = [
    "FakeClient",
    "FakeResult",
    "FakeTooManyRequests",
    "FakeTweet",
    "FakeUser",
    "install_twikit_module",
    "load_modules",
]
