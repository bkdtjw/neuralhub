from __future__ import annotations

from itertools import groupby

from pydantic import BaseModel, Field


class ReportItem(BaseModel):
    site: str
    title: str
    summary: str
    url: str
    image_key: str = ""


class MorningReport(BaseModel):
    date: str
    items: list[ReportItem] = Field(default_factory=list)


def build_morning_report_card(report: MorningReport) -> dict:
    elements: list[dict] = []
    sorted_items = sorted(report.items, key=lambda item: item.site)
    for site, group in groupby(sorted_items, key=lambda item: item.site):
        elements.append({"tag": "markdown", "content": f"**{site}**"})
        for item in group:
            elements.extend(_item_elements(item))
    if not elements:
        elements.append({"tag": "markdown", "content": "No report items."})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"Morning Report {report.date}"},
        },
        "elements": elements,
    }


def _item_elements(item: ReportItem) -> list[dict]:
    content = f"[{item.title}]({item.url})\n{item.summary}"
    elements: list[dict] = [{"tag": "markdown", "content": content}]
    if item.image_key:
        elements.append(
            {
                "tag": "img",
                "img_key": item.image_key,
                "alt": {"tag": "plain_text", "content": item.title[:40] or "image"},
            }
        )
    return elements


__all__ = ["MorningReport", "ReportItem", "build_morning_report_card"]
