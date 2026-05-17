from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from backend.common.logging import get_logger
from backend.common.message_history import sanitize_message_history
from backend.common.types import Message

from .checkpoint import CheckpointFn
from .plan_models import TodoStep

if TYPE_CHECKING:
    from .agent_loop import AgentLoop

logger = get_logger(component="plan_execute_runner")
MAX_STEP_SESSION_ID_LENGTH = 64


def adapter_provider_name(adapter: object | None) -> str:
    return adapter.__class__.__name__ if adapter is not None else ""


def make_step_session_id(session_id: str, plan_name: str, step_id: int) -> str:
    raw = f"{session_id}-plan-{plan_name}-step-{step_id}"
    if len(raw) <= MAX_STEP_SESSION_ID_LENGTH:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"plan-step-{digest}-{step_id}"


def make_step_checkpoint_fn(step_session_id: str) -> CheckpointFn:
    async def checkpoint(_sid: str, message: Message) -> None:
        from backend.storage import SessionStore

        store = SessionStore()
        await store.add_messages(step_session_id, [message])

    return checkpoint


async def prepare_step_checkpoint(loop: AgentLoop, todo_step: TodoStep, provider: str) -> None:
    step_session_id = todo_step.checkpoint_session_id
    if not step_session_id:
        return
    from backend.storage import SessionStore

    store = SessionStore()
    await store.ensure_session(
        step_session_id,
        model=loop._config.model,
        provider=provider,
        system_prompt=_checkpoint_system_prompt(loop),
    )
    existing = await store.get_messages(step_session_id)
    if existing:
        loop.message_history.restore(_restore_step_messages(loop, existing))
        logger.info(
            "plan_step_checkpoint_restored",
            step_id=todo_step.id,
            message_count=len(existing),
        )
        return
    prompt = _checkpoint_system_prompt(loop)
    if prompt:
        system = Message(role="system", content=prompt)
        await store.add_messages(step_session_id, [system])
        loop.message_history.restore([system])


def _restore_step_messages(loop: AgentLoop, messages: list[Message]) -> list[Message]:
    prompt = _checkpoint_system_prompt(loop)
    restored = (
        [Message(role="system", content=prompt), *messages]
        if prompt and (not messages or messages[0].role != "system")
        else list(messages)
    )
    return sanitize_message_history(restored)


def _checkpoint_system_prompt(loop: AgentLoop) -> str:
    if loop._config.system_prompt:
        return loop._config.system_prompt
    messages = getattr(loop, "_static_skill_messages", [])
    return str(messages[0].content) if messages else ""


__all__ = [
    "_restore_step_messages",
    "adapter_provider_name",
    "make_step_checkpoint_fn",
    "make_step_session_id",
    "prepare_step_checkpoint",
]
