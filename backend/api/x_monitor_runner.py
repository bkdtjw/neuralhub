from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import FastAPI

from backend.api.x_search_service import XSearchQuery, XSearchResult, run_x_search
from backend.common.logging import get_logger
from backend.common.metrics import incr
from backend.common.x_budget import XBudgetError
from backend.config.settings import settings
from backend.core.s02_tools.builtin.feishu_notify import create_feishu_notify_tool
from backend.core.s02_tools.builtin.x_client import XClientConfig, XPost
from backend.storage.x_monitor_models import XMonitor
from backend.storage.x_monitor_store import XMonitorStore

logger = get_logger(component="x_monitor_runner")

SearchFn = Callable[[XMonitor], Awaitable[XSearchResult]]
NotifyFn = Callable[[XMonitor, XPost, str], Awaitable[bool]]


def crossing_reason(monitor: XMonitor, post: XPost) -> str:
    """返回命中原因；未过阈值返回空串。阈值为 0 表示该维度不参与判定。"""
    if monitor.threshold_likes > 0 and post.likes >= monitor.threshold_likes:
        return f"likes>={monitor.threshold_likes}"
    if monitor.threshold_views > 0 and post.views >= monitor.threshold_views:
        return f"views>={monitor.threshold_views}"
    return ""


async def process_monitor(
    store: XMonitorStore, monitor: XMonitor, search: SearchFn, notify: NotifyFn, now: datetime
) -> str:
    """跑一条监控：搜索 → 过阈值 → 去重入库 → 新命中告警。返回本轮状态。"""
    try:
        result = await search(monitor)
    except XBudgetError:
        return "budget"
    except Exception as exc:  # noqa: BLE001
        logger.warning("x_monitor_search_failed", monitor_id=monitor.id, error=str(exc))
        return "error"
    for post in result.posts:
        reason = crossing_reason(monitor, post)
        if not reason:
            continue
        hit_id = await store.insert_hit({
            "monitor_id": monitor.id,
            "tweet_url": post.url,
            "author_handle": post.author_handle,
            "text_snippet": post.text[:500],
            "likes": post.likes,
            "views": post.views,
            "hit_reason": reason,
        })
        if hit_id is None:
            continue  # 同推文已记过（UNIQUE 去重）→ 不重复告警
        await incr("x_monitor_hits")
        sent = await notify(monitor, post, reason)
        await store.set_hit_notified(hit_id, sent)
    return "rate_limited" if result.rate_limited else "ok"


async def run_monitor_cycle(
    store: XMonitorStore, search: SearchFn, notify: NotifyFn, now: datetime
) -> None:
    """一个 tick：处理所有到期监控。单条监控异常只标 error，绝不打断其余监控。"""
    for monitor in await store.list_due(now):
        try:
            status = await process_monitor(store, monitor, search, notify, now)
        except Exception as exc:  # noqa: BLE001
            logger.exception("x_monitor_process_failed", monitor_id=monitor.id, error=str(exc))
            status = "error"
        try:
            await store.mark_run(monitor.id, status, now)
        except Exception:  # noqa: BLE001
            logger.exception("x_monitor_mark_run_failed", monitor_id=monitor.id)


def _default_search() -> SearchFn:
    config = XClientConfig(
        username=settings.twitter_username,
        email=settings.twitter_email,
        password=settings.twitter_password,
        proxy_url=settings.twitter_proxy_url,
        cookies_file=settings.twitter_cookies_file,
    )

    async def search(monitor: XMonitor) -> XSearchResult:
        query = XSearchQuery(
            query=monitor.query,
            days=monitor.days_window,
            limit=settings.x_monitor_search_limit,
            search_type=monitor.search_type,
        )
        # 只扣日额度、不过 5s 间隔闸：轮询天然被 tick+进程锁串行化，与 /compare 同策略。
        return await run_x_search(config, query, enforce_interval=False)

    return search


def _default_notify() -> NotifyFn:
    _, execute = create_feishu_notify_tool(
        settings.feishu_webhook_url, settings.feishu_webhook_secret or None
    )

    async def notify(monitor: XMonitor, post: XPost, reason: str) -> bool:
        content = (
            f"关键词：{monitor.query}\n@{post.author_handle}（{post.author_name}）\n"
            f"{post.text[:300]}\n赞 {post.likes:,} · 浏览 {post.views:,}（{reason}）\n{post.url}"
        )
        result = await execute({"content": content, "title": f"🔥 X 监控命中：{monitor.query}"})
        if result.is_error:
            logger.warning("x_monitor_notify_failed", monitor_id=monitor.id, error=result.output)
            return False
        await incr("x_monitor_alerts")
        return True

    return notify


async def run_x_monitor_loop(shutdown_event: asyncio.Event) -> None:
    store, search, notify = XMonitorStore(), _default_search(), _default_notify()
    logger.info("x_monitor_runner_started", tick_seconds=settings.x_monitor_tick_seconds)
    try:
        while not shutdown_event.is_set():
            try:
                await run_monitor_cycle(store, search, notify, datetime.utcnow())
            except Exception:  # noqa: BLE001
                # 单轮任意异常都不能杀死循环：记录后进入下一轮，保持监控常驻。
                logger.exception("x_monitor_cycle_failed")
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=settings.x_monitor_tick_seconds
                )
            except TimeoutError:
                continue
    except asyncio.CancelledError:
        return


def start_x_monitor_runner(app: FastAPI) -> None:
    # 幂等：已有任务则不重复启动；开关关闭则不启动。
    if not settings.x_monitor_enabled or getattr(app.state, "x_monitor_task", None) is not None:
        return
    try:
        shutdown_event = asyncio.Event()
        app.state.x_monitor_shutdown = shutdown_event
        app.state.x_monitor_task = asyncio.create_task(
            run_x_monitor_loop(shutdown_event), name="x-monitor-runner"
        )
    except Exception:  # noqa: BLE001
        # 监控是尽力而为的后台能力，启动失败不应拖垮 API 生命周期。
        logger.exception("x_monitor_runner_start_failed")


async def stop_x_monitor_runner(app: FastAPI) -> None:
    task = getattr(app.state, "x_monitor_task", None)
    shutdown_event = getattr(app.state, "x_monitor_shutdown", None)
    if task is None:
        return
    try:
        if shutdown_event is not None:
            shutdown_event.set()
        await asyncio.gather(task, return_exceptions=True)
    except Exception:  # noqa: BLE001
        logger.exception("x_monitor_runner_stop_failed")
    finally:
        app.state.x_monitor_task = None
        app.state.x_monitor_shutdown = None


__all__ = [
    "crossing_reason",
    "process_monitor",
    "run_monitor_cycle",
    "run_x_monitor_loop",
    "start_x_monitor_runner",
    "stop_x_monitor_runner",
]
