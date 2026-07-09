from __future__ import annotations

import json

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import LLMRequest, Message
from backend.core.system_prompt import COMPRESSION_RETENTION_TEMPLATE

from .boundary import align_recent_boundary
from .summary_helpers import build_summary_message, is_summary_message
from .threshold_policy import ThresholdPolicy

SUMMARY_SYSTEM_PROMPT = """
你是对话历史压缩器。你的任务是把较早的 agent 对话压缩成继续工作的摘要。
{retention_template}
输出必须使用以下结构，字段不可省略：
<structured_summary>
  <goal>用户当前的最终目标</goal>
  <constraints>
    - 用户明确说过"不要做"的事
    - 用户纠正过的判断
  </constraints>
  <identifiers>文件路径、商品ID、URL、订单号等关键标识符，原样保留</identifiers>
  <decisions>已做出的选择和原因</decisions>
  <failures>失败过的路径、原因、替换策略</failures>
  <pending>还没完成的事项</pending>
  <narrative>用 3-5 句话概述到目前为止发生了什么</narrative>
</structured_summary>
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
            summary_messages = [
                message for message in messages if message.role != "system" and is_summary_message(message)
            ]
            non_system_messages = [
                message
                for message in messages
                if message.role != "system" and not is_summary_message(message)
            ]
            reserve_count = self._policy.get_reserve_count()
            if len(non_system_messages) <= reserve_count:
                return list(messages)
            old_messages, recent_messages = align_recent_boundary(
                non_system_messages, reserve_count
            )
            if not old_messages:
                return list(messages)
            summary_error = ""
            try:
                summary = await self._request_summary(old_messages)
            except ContextCompressionError as exc:
                summary = self._build_fallback_summary(old_messages)
                summary_error = exc.message
            summary_message = build_summary_message(summary, error=summary_error)
            return [*system_messages, *summary_messages, summary_message, *recent_messages]
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
                max_tokens=5000,
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
            "必须遵守 P1-P6 保留优先级，并按 system 中的 structured_summary XML 格式输出。",
            "没有内容的字段写“无”。",
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
        lines = []
        for index, message in enumerate(messages, start=1):
            preview = self._clip_text(self._render_message(message, tool_names), 100)
            lines.append(f"{index}. {preview}")
        details = "\n".join(lines) or "无"
        return (
            "<structured_summary>\n"
            "  <goal>摘要模型调用失败，需基于降级摘要继续。</goal>\n"
            "  <constraints>无</constraints>\n"
            "  <identifiers>降级摘要可能不完整，关键标识符需回查历史。</identifiers>\n"
            "  <decisions>无</decisions>\n"
            "  <failures>摘要模型调用失败，已按较早消息截断生成摘要。</failures>\n"
            f"  <pending>{self._clip_text(details, 1800)}</pending>\n"
            "  <narrative>较早历史已被降级压缩，继续任务前应优先确认关键约束和路径。</narrative>\n"
            "</structured_summary>"
        )

    def _build_fallback_messages(
        self,
        messages: list[Message],
        error: ContextCompressionError,
    ) -> list[Message]:
        system_messages = [message for message in messages if message.role == "system"]
        summary_messages = [
            message for message in messages if message.role != "system" and is_summary_message(message)
        ]
        non_system_messages = [
            message
            for message in messages
            if message.role != "system" and not is_summary_message(message)
        ]
        reserve_count = self._policy.get_reserve_count()
        old_messages, recent_messages = align_recent_boundary(non_system_messages, reserve_count)
        summary = self._build_fallback_summary(old_messages)
        summary_message = build_summary_message(summary, error=error.message)
        return [*system_messages, *summary_messages, summary_message, *recent_messages]

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        truncated = len(text) - limit
        return f"{text[:limit]}...[truncated {truncated} chars]"


__all__ = ["ContextCompressor"]
