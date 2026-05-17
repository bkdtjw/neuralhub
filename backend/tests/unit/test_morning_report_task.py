from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.s02_tools.builtin.article_extractor import Article
from backend.core.s02_tools.builtin.browser import PageResult, SiteConfig
from backend.core.s07_task_system.tasks import morning_report_task as module
from backend.core.s07_task_system.tasks.morning_report_task import (
    MorningReportConfig,
    MorningReportDeps,
    run_morning_report,
)
from backend.storage.asset_store import AssetStore
from backend.storage.run_trace_store import RunTraceStore


class FakeFeishuClient:
    def __init__(self) -> None:
        self.cards: list[dict] = []
        self.uploads: list[Path] = []

    async def upload_image(self, file_path: str | Path) -> str:
        self.uploads.append(Path(file_path))
        return "img_key"

    async def send_card(self, chat_id: str, card_content: dict) -> str:
        self.cards.append(card_content)
        return "message-id"


@pytest.mark.asyncio
async def test_morning_report_archives_and_sends_card(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
    tmp_path: Path,
) -> None:
    screenshot = tmp_path / "shot.png"
    screenshot.write_bytes(b"png")

    async def fake_load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
        return PageResult(url=url, html="<html></html>", screenshot_path=screenshot)

    async def fake_extract_article(
        html: str,
        url: str,
        site_config: SiteConfig | None = None,
    ) -> Article:
        return Article(url=url, title="Title", body="Body", images=[])

    monkeypatch.setattr(module, "load_url", fake_load_url)
    monkeypatch.setattr(module, "extract_article", fake_extract_article)
    client = FakeFeishuClient()
    result = await run_morning_report(
        MorningReportConfig(user_id="u1", chat_id="chat"),
        MorningReportDeps(
            feishu_client=client,
            asset_store=AssetStore(root=tmp_path),
            trace_store=RunTraceStore(db_session_factory),
            site_configs=[
                SiteConfig(name="site1", domain="example.com", entry_url="https://e.test")
            ],
        ),
    )
    assert result["success"] is True
    assert client.cards
    assert client.cards[0]["header"]["title"]["content"].startswith("Morning Report")
    assert client.uploads[0].exists()
    assert list(tmp_path.glob("*/morning_report/screenshots/*.png"))
    assert list(tmp_path.glob("*/morning_report/reports/report.md"))
