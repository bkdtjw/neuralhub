from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from backend.api.routes import feishu_card_approval
from backend.api.routes.feishu_tool_approval import send_tool_approval_card
from backend.schemas.feishu import FeishuCardAction, FeishuCardActionPayload, FeishuCardActionValue


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer。
    yield


pytestmark = pytest.mark.asyncio


class _RecordingClient:
    """记录 send_card / update_card 调用，并为每次发送返回独立 message_id。"""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self._counter = 0

    async def send_card(self, chat_id: str, card_content: dict[str, Any]) -> str:
        self._counter += 1
        message_id = f"om_{self._counter}"
        self.sent.append((message_id, card_content))
        return message_id

    async def update_card(self, message_id: str, card_content: dict[str, Any]) -> bool:
        self.updated.append((message_id, card_content))
        return True


class _Handler:
    def __init__(self, client: _RecordingClient) -> None:
        self._client = client

    def resolve_tool_call(self, chat_id: str, tool_call_id: str, approved: bool, owner_id: str) -> bool:
        return True


class _Config:
    session_id = "feishu-oc_1"


class _Loop:
    _owner_id = "ou_1"
    _config = _Config()


def _calls() -> list[dict[str, Any]]:
    return [
        {"id": "call_1", "name": "send_email", "arguments": {"to": "a@example.com"}},
        {"id": "call_2", "name": "delete_file", "arguments": {"path": "/tmp/x"}},
    ]


def _action_blocks(card: dict[str, Any]) -> list[dict[str, Any]]:
    return [element for element in card["elements"] if element.get("tag") == "action"]


def _card_tool_id(card: dict[str, Any]) -> str:
    blocks = _action_blocks(card)
    return str(blocks[0]["actions"][0]["value"]["tool_call_id"])


async def test_multi_tool_sends_one_card_per_tool() -> None:
    client = _RecordingClient()
    await send_tool_approval_card(_Handler(client), "oc_1", _Loop(), {"tool_calls": _calls()})

    # N 个工具 → N 条独立消息（N 次 send_card，N 个不同 message_id）。
    assert len(client.sent) == 2
    message_ids = [mid for mid, _ in client.sent]
    assert len(set(message_ids)) == 2

    # 每张卡只含一个工具：一个 action 块、一个 tool_call_id、同意+拒绝两个按钮。
    seen_ids: set[str] = set()
    for _mid, card in client.sent:
        blocks = _action_blocks(card)
        assert len(blocks) == 1
        buttons = blocks[0]["actions"]
        assert len(buttons) == 2
        ids = {button["value"]["tool_call_id"] for button in buttons}
        assert len(ids) == 1
        seen_ids |= ids
    assert seen_ids == {"call_1", "call_2"}


@pytest.mark.parametrize("count", [1, 3])
async def test_card_count_matches_tool_count(count: int) -> None:
    client = _RecordingClient()
    calls = [{"id": f"call_{i}", "name": f"tool_{i}", "arguments": {}} for i in range(count)]
    await send_tool_approval_card(_Handler(client), "oc_1", _Loop(), {"tool_calls": calls})
    assert len(client.sent) == count
    assert len({mid for mid, _ in client.sent}) == count


async def test_click_one_updates_only_its_own_card(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient()
    handler = _Handler(client)
    await send_tool_approval_card(handler, "oc_1", _Loop(), {"tool_calls": _calls()})

    id_to_message = {_card_tool_id(card): mid for mid, card in client.sent}

    monkeypatch.setattr(feishu_card_approval, "_get_handler", lambda: handler)
    payload = FeishuCardActionPayload(
        open_id="ou_1",
        open_message_id=id_to_message["call_1"],
        action=FeishuCardAction(
            value=FeishuCardActionValue(
                action="tool_approve",
                tool_call_id="call_1",
                tool_name="send_email",
                chat_id="oc_1",
                owner_id="ou_1",
            )
        ),
    )
    result = await feishu_card_approval.handle_tool_approve(payload)

    # 只替换了 call_1 对应的那条消息；call_2 的审批卡（含按钮）完全不受影响。
    assert result["toast"]["type"] == "info"
    assert len(client.updated) == 1
    updated_message_id = client.updated[0][0]
    assert updated_message_id == id_to_message["call_1"]
    assert updated_message_id != id_to_message["call_2"]

    call_2_card = next(card for mid, card in client.sent if mid == id_to_message["call_2"])
    assert len(_action_blocks(call_2_card)) == 1
