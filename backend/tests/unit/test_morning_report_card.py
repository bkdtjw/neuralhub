from __future__ import annotations

from backend.core.s02_tools.builtin.feishu_cards import (
    MorningReport,
    ReportItem,
    build_morning_report_card,
)


def test_build_morning_report_card_groups_items() -> None:
    card = build_morning_report_card(
        MorningReport(
            date="2026-05-13",
            items=[
                ReportItem(
                    site="HN",
                    title="Launch",
                    summary="A short summary",
                    url="https://news.ycombinator.com/item?id=1",
                    image_key="img_key",
                )
            ],
        )
    )
    assert card["header"]["title"]["content"] == "Morning Report 2026-05-13"
    assert card["elements"][0]["content"] == "**HN**"
    assert "Launch" in card["elements"][1]["content"]
    assert card["elements"][2]["img_key"] == "img_key"
