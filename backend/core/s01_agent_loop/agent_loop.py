from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    AgentEvent,
    AgentEventHandler,
    AgentEventType,
    AgentStatus,
    Message,
    SecurityPolicy,
)
from backend.core.s02_tools import SecurityGate, ToolExecutor, ToolRegistry
from backend.core.s06_context_compression import ContextCompressor, ThresholdPolicy, TokenCounter

from .checkpoint import CheckpointFn
from .agent_loop_approval import AgentLoopApprovalMixin
from .agent_loop_run import run_agent_loop
from .message_history import MessageHistory
from .tool_review import ToolReviewContext
from .user_config_store import UserConfigStore

if TYPE_CHECKING:
    from backend.core.s02_tools.mcp import BridgeProtocol
    from backend.core.s05_skills.models import AgentSpec
else:
    AgentSpec = Any


class AgentLoop(AgentLoopApprovalMixin):
    def __init__(
        self,
        config: AgentConfig,
        adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        compressor: ContextCompressor | None = None,
        security_policy: SecurityPolicy | None = None,
        checkpoint_fn: CheckpointFn | None = None,
        bridge: BridgeProtocol | None = None,
        agent_spec: AgentSpec | None = None,
        owner_id: str = "unknown",
        user_config_store: UserConfigStore | None = None,
        tool_review_context: ToolReviewContext | None = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._bridge = bridge
        self._agent_spec = agent_spec
        self._owner_id = owner_id or "unknown"
        self._user_config_store = user_config_store or UserConfigStore()
        self._tool_review_context = tool_review_context or ToolReviewContext()
        self._executor = ToolExecutor(tool_registry)
        self._security_gate = SecurityGate(
            policy=security_policy or SecurityPolicy(allowed_tools=[], dangerous_tools=[]),
            registry=tool_registry,
        )
        self._compressor = compressor or ContextCompressor(
            adapter=adapter,
            model=config.model,
            policy=ThresholdPolicy(),
        )
        self._token_counter = TokenCounter()
        self._history = MessageHistory(checkpoint_fn=checkpoint_fn, session_id=config.session_id)
        self._status: AgentStatus = "idle"
        self._handlers: list[AgentEventHandler] = []
        self._tool_approval_events: dict[str, asyncio.Event] = {}
        self._tool_approval_decisions: dict[str, bool] = {}
        self._tool_approval_reasons: dict[str, str] = {}
        self._tool_approval_timeout_seconds = 300.0
        self._aborted = False

    def on(self, handler: AgentEventHandler) -> None:
        self._handlers.append(handler)

    def _emit(self, event_type: AgentEventType, data: Any = None) -> None:
        event = AgentEvent(type=event_type, data=data)
        for handler in self._handlers:
            result = handler(event)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)

    def _set_status(self, status: AgentStatus) -> None:
        self._status = status
        self._emit("status_change", status)

    def _ensure_system_message(self) -> None:
        self._history.ensure_system_message(self._config.system_prompt)

    async def _append_message(self, message: Message) -> None:
        await self._history.append(message)

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def messages(self) -> list[Message]:
        return self._history.messages

    @property
    def message_history(self) -> MessageHistory:
        return self._history

    @property
    def bridge(self) -> BridgeProtocol | None:
        return self._bridge

    @property
    def agent_spec(self) -> AgentSpec | None:
        return self._agent_spec

    async def run(self, user_message: str) -> Message:
        return await run_agent_loop(self, user_message)

    def abort(self) -> None:
        self._aborted = True
        for event in self._tool_approval_events.values():
            event.set()

    def reset(self) -> None:
        self._history.reset()
        self._security_gate.reset()
        self._status = "idle"
        self._aborted = False

__all__ = ["AgentLoop"]
