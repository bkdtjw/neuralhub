from __future__ import annotations

import json

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import LLMRequest, Message
from backend.core.system_prompt import COMPRESSION_RETENTION_TEMPLATE

from .boundary import align_recent_boundary
from .threshold_policy import ThresholdPolicy

SUMMARY_SYSTEM_PROMPT = """
你是对话历史压缩器。你的任务是把较早的 agent 对话压缩成继续工作的摘要。
{retention_template}
必须保留：
1. 用户的核心需求与约束；
2. 已完成的操作、执行结果与关键结论；
3. 修改过、读取过或重点关注的文件路径；
4. 当前进度、已做出的技术决策；
5. 未解决的问题、风险与下一步。
不要编造信息，不要重复大段原文，优先保留可执行的事实。
""".format(retention_template=COMPRESSION_RETENTION_TEMPLATE).strip()


class ContextCompressionError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="CONTEXT_COMPRESSION_FAILED", message=message)


class ContextCompressor:
    def __init__(
        self,
        adapter: LLMAdapter,
        model: str,
        policy: ThresholdPolicy,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._policy = policy

    @property
    def policy(self) -> ThresholdPolicy:
        return self._policy

    async def compact(self, messages: list[Message]) -> list[Message]:
        try:
            system_messages = [message for message in messages if message.role == "system"]
            non_system_messages = [
                message for message in messages if message.role != "system"
            ]
            reserve_count = self._policy.get_reserve_count()
            if len(non_system_messages) <= reserve_count:
                return list(messages)
            old_messages, recent_messages = align_recent_boundary(
                non_system_messages, reserve_count
            )
            if not old_messages:
                return list(messages)
            try:
                summary = await self._request_summary(old_messages)
            except ContextCompressionError:
                summary = self._build_fallback_summary(old_messages)
            summary_message = Message(
                role="user",
                content=f"[对话历史摘要]\n{summary}",
            )
            return [*system_messages, summary_message, *recent_messages]
        except Exception as exc:  # noqa: BLE001
            error = ContextCompressionError(str(exc))
            return self._build_fallback_messages(messages, error)

    async def _request_summary(self, messages: list[Message]) -> str:
        try:
            request = LLMRequest(
                model=self._model,
                messages=[
                    Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
                    Message(role="user", content=self._build_summary_prompt(messages)),
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            response = await self._adapter.complete(request)
            summary = response.content.strip()
            if not summary:
                raise ContextCompressionError("Summary response was empty")
            return summary
        except ContextCompressionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ContextCompressionError(str(exc)) from exc

    def _build_summary_prompt(self, messages: list[Message]) -> str:
        tool_names = self._build_tool_name_index(messages)
        lines = [
            "请压缩下面的较早历史，供 agent 后续继续执行任务。",
            "输出应简洁，但必须覆盖：已完成操作、修改/读取文件、当前进度、用户目标、未解决问题。",
            "",
            "[历史开始]",
        ]
        for index, message in enumerate(messages, start=1):
            rendered = self._render_message(message, tool_names)
            lines.append(f"{index}. {self._clip_text(rendered, 1200)}")
        lines.append("[历史结束]")
        return "\n".join(lines)

    @staticmethod
    def _build_tool_name_index(messages: list[Message]) -> dict[str, str]:
        tool_names: dict[str, str] = {}
        for message in messages:
            for tool_call in message.tool_calls or []:
                tool_names[tool_call.id] = tool_call.name
        return tool_names

    def _render_message(
        self,
        message: Message,
        tool_names: dict[str, str],
    ) -> str:
        if message.role == "tool":
            return self._render_tool_message(message, tool_names)
        parts = [f"role={message.role}"]
        if message.content:
            parts.append(f"content={self._clip_text(message.content, 1000)}")
        if message.tool_calls:
            tool_summaries = [self._render_tool_call(call) for call in message.tool_calls]
            parts.append("tool_calls=" + " | ".join(tool_summaries))
        return " ; ".join(parts)

    def _render_tool_message(
        self,
        message: Message,
        tool_names: dict[str, str],
    ) -> str:
        if not message.tool_results:
            return "role=tool ; no_results"
        parts = ["role=tool"]
        for result in message.tool_results:
            tool_name = tool_names.get(result.tool_call_id, "unknown_tool")
            status = "error" if result.is_error else "ok"
            preview = self._clip_text(result.output, 200)
            parts.append(f"{tool_name}[{status}]={preview}")
        return " ; ".join(parts)

    @staticmethod
    def _render_tool_call(tool_call: object) -> str:
        name = getattr(tool_call, "name", "unknown_tool")
        arguments = getattr(tool_call, "arguments", {})
        arguments_text = json.dumps(
            arguments,
            default=str,
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{name}({ContextCompressor._clip_text(arguments_text, 200)})"

    def _build_fallback_summary(self, messages: list[Message]) -> str:
        tool_names = self._build_tool_name_index(messages)
        lines = ["以下为降级摘要，基于较早消息的前 100 字符截断生成："]
        for index, message in enumerate(messages, start=1):
            preview = self._clip_text(self._render_message(message, tool_names), 100)
            lines.append(f"{index}. {preview}")
        return "\n".join(lines)

    def _build_fallback_messages(
        self,
        messages: list[Message],
        error: ContextCompressionError,
    ) -> list[Message]:
        system_messages = [message for message in messages if message.role == "system"]
        non_system_messages = [message for message in messages if message.role != "system"]
        reserve_count = self._policy.get_reserve_count()
        old_messages, recent_messages = align_recent_boundary(non_system_messages, reserve_count)
        summary = self._build_fallback_summary(old_messages)
        summary_message = Message(
            role="user",
            content=f"[对话历史摘要]\n{summary}\n\n[压缩降级原因]\n{error.message}",
        )
        return [*system_messages, summary_message, *recent_messages]

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        truncated = len(text) - limit
        return f"{text[:limit]}...[truncated {truncated} chars]"


__all__ = ["ContextCompressor"]
