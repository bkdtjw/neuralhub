from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from backend.config.settings import Settings
from backend.storage import database


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块用 fake engine，跳过 PostgresContainer 避免拖慢。
    yield


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.run_sync_calls: list[object] = []

    async def execute(self, clause: object) -> None:
        self.executed.append(str(clause))

    async def run_sync(self, fn: object, *args: object, **kwargs: object) -> None:
        self.run_sync_calls.append(fn)


class _FakeCtx:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _FakeConnection()
        self.begin_called = False
        self.connect_called = False

    def begin(self) -> _FakeCtx:
        self.begin_called = True
        return _FakeCtx(self.connection)

    def connect(self) -> _FakeCtx:
        self.connect_called = True
        return _FakeCtx(self.connection)


def test_settings_has_auto_create_tables_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTO_CREATE_TABLES", raising=False)
    config = Settings()
    assert hasattr(config, "auto_create_tables")
    assert config.auto_create_tables is True


async def test_init_db_calls_create_all_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(database.Base.metadata, "create_all", sentinel)
    monkeypatch.setattr(database.settings, "auto_create_tables", True)
    fake_engine = _FakeEngine()

    await database.init_db(fake_engine)

    assert fake_engine.begin_called is True
    assert fake_engine.connect_called is False
    assert sentinel in fake_engine.connection.run_sync_calls


async def test_init_db_skips_create_all_when_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(database.Base.metadata, "create_all", sentinel)
    monkeypatch.setattr(database.settings, "auto_create_tables", False)
    fake_engine = _FakeEngine()

    await database.init_db(fake_engine)

    assert fake_engine.begin_called is False
    assert fake_engine.connect_called is True
    assert fake_engine.connection.run_sync_calls == []
    assert fake_engine.connection.executed == ["SELECT 1"]
