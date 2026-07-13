from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.s02_tools.builtin.collect_and_process_support import (
    PipelineConfig,
    RawTweet,
    RawVideo,
    map_video,
    map_x_post,
    process_raw_data,
)
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.tests.unit.module_reload_support import fresh_import
from backend.tests.unit.x_test_support import install_twikit_module
from backend.tests.unit.youtube_test_support import install_transcript_module


# 用"1 小时前"的时间戳，稳定落在 max_age_hours(48h)窗口内——避免硬编码日期随时间过期被策展(curation)按 stale 丢弃。
_RECENT_ISO = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def test_map_x_post_maps_client_fields() -> None:
    post = SimpleNamespace(
        author_name="Peter",
        author_handle="steipete",
        text="Claude Code shipped a useful skill workflow",
        likes="123",
        retweets="45",
        replies=6,
        views="7,890",
        created_at="Tue Mar 25 10:30:00 +0000 2026",
        url="https://x.com/steipete/status/1",
    )
    tweet = map_x_post(post)
    assert tweet.author == "@steipete (Peter)"
    assert tweet.likes == 123 and tweet.retweets == 45
    assert tweet.views == 7890 and tweet.url.endswith("/1")


def test_map_video_maps_client_fields() -> None:
    video = SimpleNamespace(
        title="AI coding tools",
        url="https://www.youtube.com/watch?v=abc",
        channel="DevReview",
        view_count="12,345",
        upload_date="2026-03-20",
        subtitle_text="Today we compare coding agents.",
    )
    mapped = map_video(video)
    assert mapped.title == "AI coding tools"
    assert mapped.channel == "DevReview" and mapped.view_count == 12345
    assert "coding agents" in mapped.subtitle_text


@pytest.mark.asyncio
async def test_process_raw_data_formats_top_items_and_limits_output() -> None:
    tweets = {
        "Claude Code": [
            _tweet("low", 1),
            _tweet("top", 40),
            _tweet("mid", 20),
            _tweet("third", 10),
        ]
    }
    videos = [RawVideo(title="Video", url="https://youtu.be/v1", channel="AI", view_count=10)]
    result = await process_raw_data(tweets, videos, PipelineConfig(max_evidence_cards=4), None)
    assert len(result.evidence_text) <= 11000
    assert result.evidence_text.index("top") < result.evidence_text.index("mid")
    assert "X counts by keyword: Claude Code: 4" in result.evidence_text
    assert "https://x.com/test/top" in result.stats["reported_ids"]


@pytest.mark.asyncio
async def test_process_raw_data_handles_empty_input() -> None:
    result = await process_raw_data({}, [], PipelineConfig(), None)
    assert result.stats["evidence_cards"] == 0
    assert "No evidence cards generated" in result.evidence_text


@pytest.mark.asyncio
async def test_execute_continues_when_keyword_and_youtube_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_collect_module(monkeypatch)
    calls: list[tuple[str, int, int]] = []

    async def fake_search_x_posts(query: str, config: object, options: Any) -> list[Any]:
        del config
        calls.append((query, options.max_results, options.days))
        if query == "bad":
            raise RuntimeError("rate limit")
        return [
            SimpleNamespace(
                author_name="Reporter",
                author_handle="reporter",
                text=f"{query} success reporting on Claude Code updates",
                likes=1,
                retweets=3,
                replies=0,
                views=500,
                created_at=_RECENT_ISO,
                url=f"https://x.com/reporter/{query}",
            )
        ]

    async def fake_search_videos(request: object) -> list[Any]:
        del request
        raise RuntimeError("quota")

    monkeypatch.setattr(module, "search_x_posts", fake_search_x_posts)
    monkeypatch.setattr(module, "search_videos", fake_search_videos)
    _, execute = module.create_collect_and_process_tool(_config(module, tmp_path))
    result = await execute(
        {
            "keywords": ["good", "bad"],
            "max_results_per_keyword": 5,
            "days": 2,
            "include_youtube": True,
            "task_id": "unit",
        }
    )
    assert result.is_error is False
    assert "good success" in result.output
    assert 'X search failed for "bad"' in result.output
    assert "YouTube search failed: quota" in result.output
    assert calls == [("good", 5, 2), ("bad", 5, 2)]
    assert "https://x.com/reporter/good" in (tmp_path / "unit_urls.json").read_text()


def test_register_builtin_tools_adds_collect_and_keeps_x_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _load_collect_module(monkeypatch)
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        workspace=".",
        mode="readonly",
        twitter_email="tester@example.com",
        twitter_password="secret",
        youtube_api_key="test-key",
    )
    assert registry.has("x_search")
    assert registry.has("collect_and_process")


def _tweet(label: str, retweets: int) -> RawTweet:
    return RawTweet(
        author="@test",
        text=f"{label} tweet discussing Claude Code release notes",
        retweets=retweets,
        views=500,
        created_at=_RECENT_ISO,
        url=f"https://x.com/test/{label}",
    )


def _load_collect_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    install_twikit_module(monkeypatch)
    install_transcript_module(monkeypatch)
    # 经 fresh_import 重导：测试结束后 sys.modules 还原为原模块。此前用
    # sys.modules.pop 重导会永久留下新 x_client 副本，令 test_x_api 的 502
    # 用例在全量顺序下因 XClientError 类身份分裂而穿透路由捕获。
    return fresh_import(
        monkeypatch,
        "backend.core.s02_tools.builtin.x_client",
        "backend.core.s02_tools.builtin.youtube_transcript_client",
        "backend.core.s02_tools.builtin.youtube_client",
        "backend.core.s02_tools.builtin.collect_and_process",
    )[-1]


def _config(module: Any, tmp_path: Path) -> Any:
    return module.CollectAndProcessConfig(
        x_config=module.XClientConfig(email="tester@example.com", password="secret"),
        youtube_api_key="test-key",
        task_state_dir=str(tmp_path),
    )
