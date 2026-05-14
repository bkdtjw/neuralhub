from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend.common.types import LLMResponse, ProviderConfig, ProviderType, ToolCall
from backend.core.s02_tools.builtin.browser_agent import main_agent_loop
from backend.core.s02_tools.builtin.browser_agent.models import (
    ActionKind,
    ActionResult,
    BrowserAction,
    BrowserAgentConfig,
    VisionObservation,
)
from backend.core.s02_tools.builtin.browser_agent.stuck_detector import StuckDetector


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


@asynccontextmanager
async def fake_smart_browse(**_kwargs):
    yield FakePage()


async def fake_observe(*_args, **_kwargs) -> VisionObservation:
    return VisionObservation(page_summary="Example page")


async def test_run_browser_agent_completes_after_three_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions = iter(
        [
            BrowserAction(kind=ActionKind.WAIT, amount=0),
            BrowserAction(kind=ActionKind.EXTRACT_TEXT),
            BrowserAction(kind=ActionKind.DONE, value="done"),
        ]
    )

    async def decide(*_args, **_kwargs) -> BrowserAction:
        return next(actions)

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", FakeController)
    monkeypatch.setattr(main_agent_loop, "observe", fake_observe)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(BrowserAgentConfig(task="finish"), object())

    assert result.success is True
    assert result.reason == "done"
    assert result.steps_taken == 3
    assert len(result.history) == 2


async def test_run_browser_agent_stops_when_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    async def decide(*_args, **_kwargs) -> BrowserAction:
        return BrowserAction(kind=ActionKind.CLICK_SELECTOR, selector="button")

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", FakeController)
    monkeypatch.setattr(main_agent_loop, "observe", fake_observe)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(
        BrowserAgentConfig(task="click forever", max_steps=10),
        object(),
    )

    assert result.success is False
    assert result.reason == "stuck"
    assert result.steps_taken == 3


async def test_run_browser_agent_stops_at_max_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    async def decide(*_args, **_kwargs) -> BrowserAction:
        return BrowserAction(kind=ActionKind.SCROLL, direction="down", amount=1)

    class ChangingController(FakeController):
        count = 0

        async def take_screenshot(self) -> bytes:
            self.__class__.count += 1
            return f"shot-{self.count}".encode()

    monkeypatch.setattr(main_agent_loop, "smart_browse", fake_smart_browse)
    monkeypatch.setattr(main_agent_loop, "BrowserController", ChangingController)
    monkeypatch.setattr(main_agent_loop, "observe", fake_observe)
    monkeypatch.setattr(main_agent_loop, "main_agent_decide", decide)

    result = await main_agent_loop.run_browser_agent(
        BrowserAgentConfig(task="never done", max_steps=2),
        object(),
    )

    assert result.success is False
    assert result.reason == "max_steps"
    assert result.steps_taken == 2


async def test_main_agent_decide_parses_tool_call() -> None:
    class FakeAdapter:
        async def complete(self, request):
            self.request = request
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="done", arguments={"content": "answer"})],
            )

    class FakeRouter:
        adapter = FakeAdapter()

        async def resolve_provider(self, role: str, provider_id: str = "") -> ProviderConfig:
            return ProviderConfig(
                id="text-provider",
                name=role,
                provider_type=ProviderType.OPENAI_COMPAT,
                base_url="https://example.com",
                default_model="model",
            )

        async def get_adapter(self, provider_id: str) -> FakeAdapter:
            return self.adapter

    router = FakeRouter()
    action = await main_agent_loop.main_agent_decide(
        "task",
        [],
        "https://example.com",
        "Example",
        VisionObservation(page_summary="summary"),
        router,
    )

    assert action.kind == ActionKind.DONE
    assert action.value == "answer"
    assert router.adapter.request.tool_choice == "any"


def test_stuck_detector_detects_repeated_state() -> None:
    detector = StuckDetector(window=3)

    assert detector.is_stuck("u", b"same", "click") is False
    assert detector.is_stuck("u", b"same", "click") is False
    assert detector.is_stuck("u", b"same", "click") is True
