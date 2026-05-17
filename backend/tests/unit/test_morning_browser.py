from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.core.s02_tools.builtin.browser import SiteConfig, load_url
from backend.core.s02_tools.builtin.browser import navigation


class FakeKeyboard:
    async def press(self, key: str) -> None:
        self.key = key


class FakeLocator:
    @property
    def first(self) -> FakeLocator:
        return self

    async def click(self, timeout: int) -> None:
        raise RuntimeError(f"not visible within {timeout}")


class FakePage:
    url = "https://news.ycombinator.com/"

    def __init__(self, screenshot_file: Path) -> None:
        self.keyboard = FakeKeyboard()
        self.screenshot_file = screenshot_file
        self.routes: list[tuple[str, Any]] = []

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append((pattern, handler))

    async def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.url = url
        self.wait_until = wait_until
        self.timeout = timeout

    async def content(self) -> str:
        return "<html><title>HN</title><body>news</body></html>"

    async def screenshot(self, path: str, full_page: bool) -> None:
        Path(path).write_bytes(b"png")

    async def evaluate(self, script: str) -> bool:
        return False

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator()


class FakeBrowserSession:
    def __init__(self, user_id: str, storage_state_path: Path | None) -> None:
        self.user_id = user_id
        self.storage_state_path = storage_state_path

    async def __aenter__(self) -> FakeBrowserSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def new_page(self) -> FakePage:
        return FakePage(Path("/tmp/unused.png"))


@pytest.mark.asyncio
async def test_load_url_returns_html_and_screenshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(navigation, "BrowserSession", FakeBrowserSession)
    result = await load_url(
        "https://news.ycombinator.com/",
        SiteConfig(screenshot_dir=tmp_path),
    )
    assert result.url == "https://news.ycombinator.com/"
    assert "news" in result.html
    assert result.screenshot_path is not None
    assert result.screenshot_path.exists()
    assert result.login_required is False
    assert result.unhandled_popup is False
