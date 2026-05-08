"""Tests for CardFormatter with mock LLM adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.feishu_card import CardRegistry
from backend.common.feishu_card_formatter import (
    CardFormatter,
    _build_fallback,
    _clean_llm_json,
)
from backend.common.types import LLMResponse

_SAMPLE_CONFIG: dict = {
    "cards": {
        "search_result": {
            "template_id": "ctp_test",
            "template_version": "1.0.0",
            "description": "搜索结果卡片",
            "trigger_tools": ["x_search"],
            "variables": {
                "title": {"type": "string", "required": True, "description": "标题"},
                "summary": {"type": "string", "required": True, "description": "摘要"},
            },
        },
    },
}


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "feishu_cards.json"
    p.write_text(json.dumps(_SAMPLE_CONFIG), encoding="utf-8")
    return p


@pytest.fixture
def registry(config_file: Path) -> CardRegistry:
    r = CardRegistry(config_file)
    r.load(force=True)
    return r


def _make_adapter(response_content: str) -> AsyncMock:
    adapter = AsyncMock(spec=LLMAdapter)
    adapter.complete = AsyncMock(
        return_value=LLMResponse(content=response_content),
    )
    return adapter


class TestCardFormatter:
    @pytest.mark.asyncio
    async def test_format_returns_variables(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('{"title": "Hello", "summary": "World"}')
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format(
            "search_result",
            "Agent reply",
            "x_search",
            {"query": "test"},
            registry,
        )
        assert result == {"title": "Hello", "summary": "World"}

    @pytest.mark.asyncio
    async def test_format_strips_markdown_fences(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('```json\n{"title": "Hi", "summary": "Desc"}\n```')
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format(
            "search_result",
            "Reply",
            "x_search",
            {},
            registry,
        )
        assert result["title"] == "Hi"

    @pytest.mark.asyncio
    async def test_format_invalid_json_returns_fallback(self, registry: CardRegistry) -> None:
        adapter = _make_adapter("not json at all")
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format("search_result", "Reply", "x_search", {}, registry)
        # Should return fallback, not raise
        assert "title" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_format_non_object_returns_fallback(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('["not", "an", "object"]')
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format("search_result", "Reply", "x_search", {}, registry)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_format_coerces_values_to_str(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('{"title": 123, "summary": true}')
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format(
            "search_result",
            "Reply",
            "x_search",
            {},
            registry,
        )
        assert result["title"] == "123"
        assert result["summary"] == "true"

    @pytest.mark.asyncio
    async def test_format_retries_dirty_json(self, registry: CardRegistry) -> None:
        adapter = AsyncMock(spec=LLMAdapter)
        adapter.complete = AsyncMock(
            side_effect=[
                LLMResponse(content="not json at all"),
                LLMResponse(content='{"title": "Retried", "summary": "Clean"}'),
            ],
        )
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format("search_result", "Reply", "x_search", {}, registry)

        assert result == {"title": "Retried", "summary": "Clean"}
        assert adapter.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_format_fills_missing_variable(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('{"title": "Only title"}')
        formatter = CardFormatter(adapter, "test-model")

        result = await formatter.format(
            "search_result",
            "# Daily\n\n## 今日必看\n- Important item",
            "x_search",
            {},
            registry,
        )

        assert result["title"] == "Only title"
        assert "Important item" in result["summary"]

    @pytest.mark.asyncio
    async def test_existing_variables_skip_llm(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('{"title": "Should not be called"}')
        formatter = CardFormatter(adapter, "test-model")

        # Both variables already provided — LLM should NOT be called
        result = await formatter.format(
            "search_result",
            "Reply",
            "x_search",
            {},
            registry,
            existing_variables={"title": "Existing", "summary": "Existing summary"},
        )
        assert result == {}
        adapter.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_variables_partial(self, registry: CardRegistry) -> None:
        adapter = _make_adapter('{"summary": "LLM generated"}')
        formatter = CardFormatter(adapter, "test-model")

        # title already provided, only summary needs LLM
        result = await formatter.format(
            "search_result",
            "Reply",
            "x_search",
            {},
            registry,
            existing_variables={"title": "Existing Title"},
        )
        assert result == {"summary": "LLM generated"}
        adapter.complete.assert_called_once()


class TestCleanLlmJson:
    def test_plain_json(self) -> None:
        assert _clean_llm_json('{"a": 1}') == '{"a": 1}'

    def test_markdown_fenced(self) -> None:
        raw = '```json\n{"a": 1}\n```'
        assert json.loads(_clean_llm_json(raw)) == {"a": 1}

    def test_prefix_noise(self) -> None:
        raw = 'Here is the JSON:\n{"a": 1}'
        assert json.loads(_clean_llm_json(raw)) == {"a": 1}

    def test_trailing_noise(self) -> None:
        raw = 'Here is the JSON:\n{"a": 1}\n说明文字'
        assert json.loads(_clean_llm_json(raw)) == {"a": 1}

    def test_empty_raises(self) -> None:
        with pytest.raises(Exception, match="empty"):
            _clean_llm_json("")


class TestBuildFallback:
    def test_summary_fields_use_reply_text(self) -> None:
        from backend.schemas.feishu import FeishuCardVariableConfig

        missing = {"summary_md": FeishuCardVariableConfig(description="摘要")}
        reply = "# 科技圈 AI 早报\n\n## 今日必看\n| # | 要点 |\n|---|---|\n| 1 | Kimi 切换完成 |\n"
        result = _build_fallback(missing, reply)
        assert "科技圈 AI 早报" in result["summary_md"]
        assert "Kimi 切换完成" in result["summary_md"]

    def test_non_summary_fields_empty(self) -> None:
        from backend.schemas.feishu import FeishuCardVariableConfig

        missing = {"title": FeishuCardVariableConfig(description="标题")}
        result = _build_fallback(missing, "Reply text")
        assert result["title"] == ""
