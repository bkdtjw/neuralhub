from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class PlanControlState:
    pause_requested: bool = False
    paused: bool = False
    pending_instruction: str = ""
    _resume_event: asyncio.Event = field(default_factory=asyncio.Event)

    def request_pause(self) -> None:
        self.pause_requested = True
        self.paused = False
        self._resume_event.clear()

    def resume(self, instruction: str = "") -> None:
        instruction = instruction.strip()
        if instruction:
            self.pending_instruction = instruction
        self.pause_requested = False
        self.paused = False
        self._resume_event.set()

    def is_waiting(self) -> bool:
        return self.pause_requested or self.paused

    async def wait_until_resumed(self) -> None:
        if not self.pause_requested:
            return
        self.paused = True
        await self._resume_event.wait()

    def consume_instruction(self) -> str:
        instruction = self.pending_instruction
        self.pending_instruction = ""
        return instruction


__all__ = ["PlanControlState"]
