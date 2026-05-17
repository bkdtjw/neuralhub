from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import LLMRequest, Message

from .compressor import SUMMARY_SYSTEM_PROMPT
from .level2_compact import RECENT_KEEP_COUNT


class Level3SummaryError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="LAYERED_SUMMARY_FAILED", message=message)


@dataclass(frozen=True)
class SummaryArchiveRequest:
    messages: list[Message]
    adapter: LLMAdapter
    model: str
    sessions_dir: str
    session_id: str


async def summarize_archive(request: SummaryArchiveRequest) -> list[Message]:
    try:
        system_messages = [message for message in request.messages if message.role == "system"]
        non_system = [message for message in request.messages if message.role != "system"]
        if len(non_system) <= RECENT_KEEP_COUNT:
            return list(request.messages)
        old = non_system[:-RECENT_KEEP_COUNT]
        recent = non_system[-RECENT_KEEP_COUNT:]
        archive_path = write_session_archive(old, request.sessions_dir, request.session_id)
        try:
            summary = await request_summary(request.adapter, request.model, old)
        except Level3SummaryError:
            summary = fallback_summary(old)
        summary_message = Message(
            role="user",
            content=f"[对话历史摘要]\n{summary}\n\n[无损备份]\n{archive_path}",
        )
        return [*system_messages, summary_message, *recent]
    except Exception as exc:  # noqa: BLE001
        raise Level3SummaryError(str(exc)) from exc


async def request_summary(adapter: LLMAdapter, model: str, messages: list[Message]) -> str:
    try:
        request = LLMRequest(
            model=model,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            messages=[
                Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
                Message(role="user", content=_summary_prompt(messages)),
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        response = await adapter.complete(request)
        summary = response.content.strip()
        if not summary:
            raise Level3SummaryError("Summary response was empty")
        return summary
    except Level3SummaryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise Level3SummaryError(str(exc)) from exc


def write_session_archive(messages: list[Message], sessions_dir: str, session_id: str) -> str:
    directory = Path(sessions_dir) / (session_id or "default")
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    path = directory / f"{timestamp}.jsonl"
    lines = [message.model_dump_json() for message in messages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.as_posix()


def fallback_summary(messages: list[Message]) -> str:
    lines = ["LLM 摘要失败，以下为降级摘要，标识符和决策需必要时用 read_history 回查："]
    for index, message in enumerate(messages, start=1):
        text = message.content or _tool_text(message)
        lines.append(f"{index}. {message.role}: {_clip(text, 240)}")
    return "\n".join(lines)


def _summary_prompt(messages: list[Message]) -> str:
    lines = ["请压缩以下历史。必须遵守 P1-P6 保留优先级。", "[历史开始]"]
    for index, message in enumerate(messages, start=1):
        text = message.content or _tool_text(message)
        lines.append(f"{index}. {message.role}: {_clip(text, 1200)}")
    lines.append("[历史结束]")
    return "\n".join(lines)


def _tool_text(message: Message) -> str:
    return " | ".join(result.output for result in message.tool_results or [])


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}...[truncated {len(text) - limit} chars]"
