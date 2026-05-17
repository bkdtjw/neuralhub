from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.article_extractor import Article, extract_article
from backend.core.s02_tools.builtin.browser import PageResult, SiteConfig, load_url
from backend.core.s02_tools.builtin.feishu_cards import (
    MorningReport,
    ReportItem,
    build_morning_report_card,
)
from backend.core.s02_tools.builtin.image_filter import filter_images
from backend.storage.asset_store import AssetStore
from backend.storage.run_trace_store import RunTrace, RunTraceStore

from .morning_report_support import record_step, record_task_trace, render_markdown
from .site_loader import load_site_configs

logger = get_logger(component="morning_report_task")


class MorningReportConfig(BaseModel):
    user_id: str
    chat_id: str
    max_items_per_site: int = Field(default=3, ge=1)
    config_dir: Path = Path("config/sites")
    task_id: str = "morning_report"


class MorningReportDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feishu_client: Any = None
    asset_store: AssetStore | None = None
    trace_store: RunTraceStore | None = None
    site_configs: list[SiteConfig] | None = None


async def run_morning_report(
    config: MorningReportConfig,
    deps: MorningReportDeps | None = None,
) -> dict[str, Any]:
    resolved = deps or MorningReportDeps()
    trace_store = resolved.trace_store or RunTraceStore()
    asset_store = resolved.asset_store or AssetStore()
    started = datetime.now()
    try:
        site_configs = resolved.site_configs or load_site_configs(config.config_dir)
        items: list[ReportItem] = []
        failures = 0
        for site_config in site_configs:
            item = await _process_site(config, site_config, resolved, asset_store, trace_store)
            failures += 1 if item.title.endswith("抓取失败") else 0
            items.append(item)
        report = MorningReport(date=datetime.now().date().isoformat(), items=items)
        card = build_morning_report_card(report)
        if resolved.feishu_client is not None and config.chat_id:
            await resolved.feishu_client.send_card(config.chat_id, card)
        report_path = await asset_store.save_report(config.task_id, render_markdown(report))
        await record_task_trace(trace_store, config.task_id, started, True, report_path, items)
        return {
            "success": True,
            "items": len(items),
            "failed": failures,
            "report_path": str(report_path),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("morning_report_task_failed", error=str(exc))
        await trace_store.record(
            RunTrace(
                task_id=config.task_id,
                kind="morning_report",
                started_at=started,
                ended_at=datetime.now(),
                success=False,
                error_code="MORNING_REPORT_ERROR",
                payload_json={"error": str(exc)},
            )
        )
        return {"success": False, "items": 0, "failed": 0, "error": str(exc)}


async def _process_site(
    config: MorningReportConfig,
    site_config: SiteConfig,
    deps: MorningReportDeps,
    asset_store: AssetStore,
    trace_store: RunTraceStore,
) -> ReportItem:
    site = site_config.name or site_config.domain or "unknown"
    url = site_config.entry_url or f"https://{site_config.domain}"
    started = datetime.now()
    try:
        page = await load_url(url, site_config.model_copy(update={"user_id": config.user_id}))
        await record_step(trace_store, config.task_id, "load_url", page.url, started, True, page)
        article = await _extract_and_save(
            config.task_id,
            page,
            site_config,
            asset_store,
            trace_store,
        )
        filtered = filter_images(article.images, site_config)
        image_key = await _upload_screenshot(config.task_id, page, deps, asset_store)
        summary = article.body.strip().replace("\n", " ")[:240]
        return ReportItem(
            site=site,
            title=article.title or page.url,
            summary=summary or f"{len(filtered)} image candidates",
            url=article.url or page.url,
            image_key=image_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("morning_report_site_failed", site=site, error=str(exc))
        await record_step(
            trace_store,
            config.task_id,
            "site_failed",
            url,
            started,
            False,
            str(exc),
        )
        return ReportItem(site=site, title=f"{site} 抓取失败", summary=str(exc), url=url)


async def _extract_and_save(
    task_id: str,
    page: PageResult,
    site_config: SiteConfig,
    asset_store: AssetStore,
    trace_store: RunTraceStore,
) -> Article:
    started = datetime.now()
    article = await extract_article(page.html, page.url, site_config)
    await asset_store.save_article(task_id, article)
    await record_step(trace_store, task_id, "extract_article", page.url, started, True, article)
    return article


async def _upload_screenshot(
    task_id: str,
    page: PageResult,
    deps: MorningReportDeps,
    asset_store: AssetStore,
) -> str:
    if page.screenshot_path is None or deps.feishu_client is None:
        return ""
    saved = await asset_store.save_screenshot(task_id, page.url, page.screenshot_path.read_bytes())
    image_key = await deps.feishu_client.upload_image(saved)
    return image_key or ""


__all__ = ["MorningReportConfig", "MorningReportDeps", "run_morning_report"]
