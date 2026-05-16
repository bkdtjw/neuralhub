from __future__ import annotations

import pytest

from backend.common.types import Message
from backend.core.s01_agent_loop import MessageHistory


@pytest.mark.asyncio
async def test_message_history_append_and_checkpoint() -> None:
    checkpoints: list[tuple[str, str]] = []

    async def checkpoint(session_id: str, message: Message) -> None:
        checkpoints.append((session_id, message.role))

    history = MessageHistory(checkpoint_fn=checkpoint, session_id="session-1")
    await history.append(Message(role="user", content="hello"))

    assert [message.role for message in history.messages] == ["user"]
    assert checkpoints == [("session-1", "user")]
    assert history.has_checkpoint_fn is True
    assert history.checkpoint_failed is False


def test_message_history_restore_extend_and_reset() -> None:
    history = MessageHistory()
    history.ensure_system_message("system")
    history.extend([Message(role="user", content="hello")])
    history.restore([Message(role="assistant", content="restored")])

    assert [message.role for message in history.messages] == ["assistant"]
    assert history.raw_messages is not history.messages

    history.reset()
    assert len(history) == 0
