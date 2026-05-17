from __future__ import annotations

from backend.common.types import LLMRequest, Message


def request_system_prompt(request: LLMRequest) -> str:
    if request.system_prompt:
        return request.system_prompt
    for message in request.messages:
        if message.role == "system":
            return message.content
    return ""


def request_zone_messages(request: LLMRequest, *, include_system: bool) -> list[Message]:
    dynamic = [
        *request.skill_messages,
        *request.memory_messages,
        *([request.summary_message] if request.summary_message else []),
        *request.recent_messages,
    ]
    messages = dynamic or request.messages
    if not include_system:
        return [message for message in messages if message.role != "system"]
    return _with_system_first(messages, request_system_prompt(request))


def _with_system_first(messages: list[Message], system_prompt: str) -> list[Message]:
    if not system_prompt:
        return list(messages)
    removed_stable = False
    remaining: list[Message] = []
    for message in messages:
        if message.role == "system" and message.content == system_prompt and not removed_stable:
            removed_stable = True
            continue
        remaining.append(message)
    return [Message(role="system", content=system_prompt), *remaining]
