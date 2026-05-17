from __future__ import annotations

from dataclasses import dataclass

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import Message, ToolResult

from .level1_artifact import sink_tool_result
from .level2_compact import compact_old_tool_summaries
from .level3_summary import Level3SummaryError, SummaryArchiveRequest, summarize_archive
from .token_counter import TokenCounter


class LayeredCompressionError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="LAYERED_COMPRESSION_FAILED", message=message)


@dataclass(frozen=True)
class LayeredCompressorConfig:
    threshold_l2: float = 0.5
    threshold_l3: float = 0.7
    artifacts_dir: str = "data/artifacts"
    sessions_dir: str = "data/sessions"
    session_id: str = ""
    max_context_tokens: int = 180000


class LayeredCompressor:
    def __init__(
        self,
        adapter: LLMAdapter,
        model: str,
        config: LayeredCompressorConfig | None = None,
    ) -> None:
        config = config or LayeredCompressorConfig()
        self._adapter = adapter
        self._model = model
        self._threshold_l2 = config.threshold_l2
        self._threshold_l3 = config.threshold_l3
        self._artifacts_dir = config.artifacts_dir
        self._sessions_dir = config.sessions_dir
        self._session_id = config.session_id
        self._max_context_tokens = config.max_context_tokens
        self._token_counter = TokenCounter()

    async def process_tool_result(self, result: ToolResult) -> ToolResult:
        try:
            return sink_tool_result(result, self._artifacts_dir, self._session_id)
        except Exception:
            return result

    async def check_and_compact(self, messages: list[Message]) -> list[Message]:
        try:
            if self._current_usage_pct(messages) > self._threshold_l2:
                return compact_old_tool_summaries(messages)
            return list(messages)
        except Exception:
            return list(messages)

    async def summarize_and_archive(self, messages: list[Message]) -> list[Message]:
        try:
            if self._current_usage_pct(messages) <= self._threshold_l3:
                return list(messages)
            return await summarize_archive(
                SummaryArchiveRequest(
                    messages=messages,
                    adapter=self._adapter,
                    model=self._model,
                    sessions_dir=self._sessions_dir,
                    session_id=self._session_id,
                )
            )
        except Level3SummaryError:
            return list(messages)
        except Exception:
            return list(messages)

    def _current_usage_pct(self, messages: list[Message]) -> float:
        tokens = self._token_counter.estimate_messages_tokens(messages)
        return tokens / max(1, self._max_context_tokens)
