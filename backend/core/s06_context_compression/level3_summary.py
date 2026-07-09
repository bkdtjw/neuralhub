from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import LLMRequest, Message

from .boundary import align_recent_boundary
from .compressor import SUMMARY_SYSTEM_PROMPT
from .level2_compact import RECENT_KEEP_COUNT
from .summary_helpers import build_summary_message, is_summary_message

SUMMARY_MARKER = "[对话历史摘要]"


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
        summary_messages = [
            message
            for message in request.messages
            if message.role != "system" and is_summary_message(message)
        ]
        non_system = [
            message
            for message in request.messages
            if message.role != "system" and not is_summary_message(message)
        ]
        if len(non_system) <= RECENT_KEEP_COUNT:
            return list(request.messages)
        old, recent = align_recent_boundary(non_system, RECENT_KEEP_COUNT)
        archive_path = write_session_archive(old, request.sessions_dir, request.session_id)
        try:
            summary = await request_summary(request.adapter, request.model, old, archive_path)
        except Level3SummaryError:
            summary = fallback_summary(old, archive_path)
        summary_message = build_summary_message(summary, archive_path)
        return [*system_messages, *summary_messages, summary_message, *recent]
    except Exception as exc:  # noqa: BLE001
        raise Level3SummaryError(str(exc)) from exc


async def request_summary(
    adapter: LLMAdapter,
    model: str,
    messages: list[Message],
    archive_path: str,
) -> str:
    try:
        request = LLMRequest(
            model=model,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            messages=[
                Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
                Message(role="user", content=_summary_prompt(messages, archive_path)),
            ],
            temperature=0.2,
            max_tokens=5000,
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


def fallback_summary(messages: list[Message], archive_path: str) -> str:
    rendered = []
    for index, message in enumerate(messages, start=1):
        text = message.content or _tool_text(message)
        rendered.append(f"{index}. {message.role}: {_clip(text, 240)}")
    details = "\n".join(rendered) or "无"
    return (
        "<structured_summary>\n"
        "  <goal>LLM 摘要失败，需基于降级摘要继续。</goal>\n"
        "  <constraints>无</constraints>\n"
        "  <identifiers>详见无损备份路径，必要时调用 read_history 回查。</identifiers>\n"
        "  <decisions>无</decisions>\n"
        "  <failures>摘要 LLM 调用失败，已生成降级摘要。</failures>\n"
        f"  <pending>{_clip(details, 1800)}</pending>\n"
        "  <narrative>较早历史已写入无损备份，继续任务时优先回查关键路径和标识符。</narrative>\n"
        "</structured_summary>\n"
        f"无损备份: {archive_path}"
    )


def _summary_prompt(messages: list[Message], archive_path: str = "") -> str:
    prior_summaries: list[str] = []
    history: list[str] = []
    for message in messages:
        text = message.content or _tool_text(message)
        if message.content and message.content.startswith(SUMMARY_MARKER):
            prior_summaries.append(text)
            continue
        history.append(f"{len(history) + 1}. {message.role}: {_clip(text, 1200)}")
    lines = [
        "请压缩以下历史。必须遵守 P1-P6 保留优先级。",
        "必须按 system 中的 structured_summary XML 格式输出。",
        f"无损备份路径：{archive_path or '无'}",
    ]
    if prior_summaries:
        lines.append("[已有摘要]")
        lines.extend(prior_summaries)
    lines.append("[历史开始]")
    lines.extend(history)
    lines.append("[历史结束]")
    return "\n".join(lines)


def _tool_text(message: Message) -> str:
    return " | ".join(result.output for result in message.tool_results or [])


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}...[truncated {len(text) - limit} chars]"
