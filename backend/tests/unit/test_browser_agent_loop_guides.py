from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend.core.s02_tools.builtin.browser_agent import main_agent_loop
from backend.core.s02_tools.builtin.browser_agent.models import (
    ActionKind,
    ActionResult,
    BrowserAction,
    BrowserAgentConfig,
    VisionObservation,
)


class FakePage:
    url = "https://example.com"

    async def title(self) -> str:
        return "Example"


class FakeController:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def take_screenshot(self) -> bytes:
        return b"same"

    async def execute(self, action: BrowserAction) -> ActionResult:
        return ActionResult(success=True, new_url=self.page.url)

    async def goto(self, url: str) -> ActionResult:
        self.page.url = url
        return ActionResult(success=True, new_url=url)


@asynccontextmanager
async def fake_smart_browse(**_kwargs):
    yield FakePage()


async def fake_observe(*_args, **_kwargs) -> VisionObservation:
    return VisionObservation(page_summary="Example page")


async def test_run_browser_agent_uses_initial_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def decide(*args, **_kwargs) -> BrowserAction:
        assert args[2] == "https://example.com/start"
        return BrowserAction(kind=ActionKind.DONE, value="done")

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", FakeController)
    monkeypatch.setattr(main_agent_loop, "observe", fake_observe)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(
        BrowserAgentConfig(task="open", initial_url="https://example.com/start"),
        object(),
    )

    assert result.success is True
    assert result.history == []


async def test_run_browser_agent_stops_fast_for_human_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeAssetStore:
        async def save_screenshot(self, task_id: str, url: str, png_bytes: bytes):
            path = tmp_path / f"{task_id}.png"
            path.write_bytes(png_bytes)
            return path

    async def observe_human_gate(*_args, **_kwargs) -> VisionObservation:
        return VisionObservation(
            page_summary="Login QR code page",
            screenshot_importance=0.9,
            screenshot_reason="需要扫码登录",
            need_human=True,
        )

    async def decide(*_args, **_kwargs) -> BrowserAction:
        raise AssertionError("decision should not run when human intervention is required")

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", FakeController)
    monkeypatch.setattr(main_agent_loop, "observe", observe_human_gate)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(
        BrowserAgentConfig(task="requires login"),
        object(),
        FakeAssetStore(),
    )

    assert result.success is False
    assert result.reason == "need_human"
    assert result.steps_taken == 1
    assert "需要扫码登录" in result.content
    assert len(result.screenshots) == 1
    assert result.screenshots[0].read_bytes() == b"same"


async def test_run_browser_agent_treats_jd_abnormal_page_as_human_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeAssetStore:
        async def save_screenshot(self, task_id: str, url: str, png_bytes: bytes):
            path = tmp_path / f"{task_id}.png"
            path.write_bytes(png_bytes)
            return path

    async def observe_abnormal_page(*_args, **_kwargs) -> VisionObservation:
        return VisionObservation(
            page_summary="当前页面异常，提示内容太火爆了，请稍后再试，并显示切换账号",
            screenshot_importance=0.2,
            need_human=False,
        )

    async def decide(*_args, **_kwargs) -> BrowserAction:
        raise AssertionError("decision should not run for JD abnormal account page")

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", FakeController)
    monkeypatch.setattr(main_agent_loop, "observe", observe_abnormal_page)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(
        BrowserAgentConfig(task="查京东商品价格", initial_url="https://www.jd.com?from=pc_search_sd"),
        object(),
        FakeAssetStore(),
    )

    assert result.success is False
    assert result.reason == "need_human"
    assert "当前页面异常" in result.content
