from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools.builtin.browser import SmartPage as ExportedSmartPage
from backend.core.s02_tools.builtin.browser import smart_browse as exported_smart_browse
from backend.core.s02_tools.builtin.browser.smart_browse import SmartPage, smart_browse

smart_browse_module = importlib.import_module("backend.core.s02_tools.builtin.browser.smart_browse")


class FakePage:
    def __init__(self) -> None:
        self.set_viewport_size = AsyncMock()
        self.route = AsyncMock()
        self.goto = AsyncMock(return_value="response")
        self.click = AsyncMock()
        self.fill = AsyncMock()
        self.url = "https://example.com/"


class FakeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[tuple[str, str]] = []

    def load_state_path(self, user_id: str, domain: str) -> Path:
        self.calls.append((user_id, domain))
        return self.path


class FakeBrowserSession:
    instances: list[FakeBrowserSession] = []

    def __init__(
        self,
        user_id: str,
        storage_state_path: Path | None = None,
        headless: bool = True,
        device_scale_factor: float = 1.0,
    ) -> None:
        self.user_id = user_id
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.device_scale_factor = device_scale_factor
        self.page = FakePage()
        self.closed = False
        FakeBrowserSession.instances.append(self)

    async def __aenter__(self) -> FakeBrowserSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.closed = True

    async def new_page(self) -> FakePage:
        return self.page


@pytest.fixture(autouse=True)
def reset_fake_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBrowserSession.instances.clear()
    monkeypatch.setattr(smart_browse_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(smart_browse_module, "install_route_blocker", AsyncMock())


@pytest.mark.asyncio
async def test_smart_browse_loads_storage_state_when_domain_set(tmp_path: Path) -> None:
    state_path = tmp_path / "storage_state.json"
    state_path.write_text("{}", encoding="utf-8")
    store = FakeStore(state_path)

    async with smart_browse(user_id="me", domain="github.com", storage_state_store=store):
        pass

    session = FakeBrowserSession.instances[-1]
    assert store.calls == [("me", "github.com")]
    assert session.storage_state_path == state_path


@pytest.mark.asyncio
async def test_smart_browse_keeps_missing_storage_state_path_for_persist(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.json"
    store = FakeStore(missing_path)

    async with smart_browse(user_id="me", domain="github.com", storage_state_store=store):
        pass

    session = FakeBrowserSession.instances[-1]
    assert session.storage_state_path == missing_path


@pytest.mark.asyncio
async def test_smart_browse_sets_viewport_and_scale() -> None:
    async with smart_browse(viewport=(800, 600), device_scale_factor=1.5) as page:
        assert isinstance(page, SmartPage)

    session = FakeBrowserSession.instances[-1]
    session.page.set_viewport_size.assert_awaited_once_with({"width": 800, "height": 600})
    assert session.device_scale_factor == 1.5


@pytest.mark.asyncio
async def test_smart_page_goto_auto_dismisses_popups(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage()
    dismiss_mock = AsyncMock(return_value=["button.close"])
    monkeypatch.setattr(smart_browse_module, "dismiss_popups", dismiss_mock)

    response = await SmartPage(page, ["button.close"]).goto(
        "https://example.com/",
        wait_until="domcontentloaded",
    )

    assert response == "response"
    page.goto.assert_awaited_once_with(
        "https://example.com/",
        wait_until="domcontentloaded",
    )
    dismiss_mock.assert_awaited_once_with(page, ["button.close"])


@pytest.mark.asyncio
async def test_smart_page_click_does_not_dismiss_popups(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage()
    dismiss_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(smart_browse_module, "dismiss_popups", dismiss_mock)

    await SmartPage(page, ["button.close"]).click("button")

    page.click.assert_awaited_once_with("button")
    dismiss_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_smart_page_passthrough_attributes_work() -> None:
    page = FakePage()
    smart_page = SmartPage(page, [])

    await smart_page.fill("input[name=q]", "hello")

    assert smart_page.url == "https://example.com/"
    assert smart_page.raw is page
    page.fill.assert_awaited_once_with("input[name=q]", "hello")
    assert exported_smart_browse is smart_browse
    assert ExportedSmartPage is SmartPage
