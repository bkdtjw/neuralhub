from __future__ import annotations

from backend.common.types import Message

from .checkpoint import CheckpointFn, safe_checkpoint


class MessageHistory:
    def __init__(
        self,
        checkpoint_fn: CheckpointFn | None = None,
        session_id: str = "",
    ) -> None:
        self._messages: list[Message] = []
        self._checkpoint_fn = checkpoint_fn
        self._session_id = session_id
        self._checkpoint_failed = False

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def raw_messages(self) -> list[Message]:
        return self._messages

    @property
    def checkpoint_failed(self) -> bool:
        return self._checkpoint_failed

    @property
    def has_checkpoint_fn(self) -> bool:
        return self._checkpoint_fn is not None

    async def append(self, message: Message) -> None:
        self._messages.append(message)
        await self._checkpoint(message)

    def ensure_system_message(self, system_prompt: str) -> None:
        if not self._messages and system_prompt:
            self._messages.append(Message(role="system", content=system_prompt))

    def restore(self, messages: list[Message]) -> None:
        self._messages = list(messages)
        self._checkpoint_failed = False

    def extend(self, messages: list[Message]) -> None:
        self._messages.extend(messages)

    def reset(self) -> None:
        self._messages.clear()
        self._checkpoint_failed = False

    async def checkpoint_from(self, start: int) -> None:
        for message in self._messages[start:]:
            await self._checkpoint(message)

    async def _checkpoint(self, message: Message) -> None:
        if not await safe_checkpoint(self._checkpoint_fn, self._session_id, message):
            self._checkpoint_failed = True

    def __len__(self) -> int:
        return len(self._messages)


__all__ = ["MessageHistory"]
