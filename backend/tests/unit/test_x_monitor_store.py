from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.storage.x_monitor_store import XMonitorStore

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 7, 10, 12, 0, 0)


def _fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "query": "claude", "interval_minutes": 15, "days_window": 1,
        "search_type": "Latest", "threshold_likes": 100, "threshold_views": 0,
        "enabled": True,
    }
    fields.update(overrides)
    return fields


def _hit_fields(monitor_id: str, url: str = "https://x.com/a/1") -> dict[str, object]:
    return {
        "monitor_id": monitor_id, "tweet_url": url, "author_handle": "a",
        "text_snippet": "hello", "likes": 150, "views": 10, "hit_reason": "likes>=100",
    }


async def test_create_get_update_delete_roundtrip() -> None:
    store = XMonitorStore()
    created = await store.create_monitor(_fields())
    assert created.query == "claude" and created.enabled is True and created.last_run_at is None

    fetched = await store.get_monitor(created.id)
    assert fetched is not None and fetched.id == created.id

    updated = await store.update_monitor(created.id, {"interval_minutes": 30, "enabled": False})
    assert updated is not None and updated.interval_minutes == 30 and updated.enabled is False
    assert updated.query == "claude"  # 未提供的字段不动

    assert await store.delete_monitor(created.id) is True
    assert await store.get_monitor(created.id) is None
    assert await store.delete_monitor(created.id) is False  # 二次删除返回 False


async def test_list_due_selects_never_run_and_overdue_only() -> None:
    store = XMonitorStore()
    never_run = await store.create_monitor(_fields(query="never"))
    overdue = await store.create_monitor(_fields(query="overdue"))
    fresh = await store.create_monitor(_fields(query="fresh"))
    disabled = await store.create_monitor(_fields(query="disabled", enabled=False))

    await store.mark_run(overdue.id, "ok", _NOW - timedelta(minutes=16))  # 16 分钟前，间隔 15 → 到期
    await store.mark_run(fresh.id, "ok", _NOW - timedelta(minutes=5))  # 5 分钟前 → 未到期

    due_ids = {monitor.id for monitor in await store.list_due(_NOW)}
    assert never_run.id in due_ids and overdue.id in due_ids
    assert fresh.id not in due_ids and disabled.id not in due_ids

    refreshed = await store.get_monitor(overdue.id)
    assert refreshed is not None and refreshed.last_status == "ok"


async def test_insert_hit_dedupes_and_cascades() -> None:
    store = XMonitorStore()
    monitor = await store.create_monitor(_fields())

    first = await store.insert_hit(_hit_fields(monitor.id))
    assert first is not None
    assert await store.insert_hit(_hit_fields(monitor.id)) is None  # 同 (monitor, url) 去重
    assert await store.insert_hit(_hit_fields(monitor.id, url="https://x.com/a/2")) is not None

    await store.set_hit_notified(first, True)
    hits = await store.list_hits(monitor.id)
    assert len(hits) == 2
    assert {hit.tweet_url: hit.notified for hit in hits}["https://x.com/a/1"] is True

    await store.delete_monitor(monitor.id)  # 级联删 hits
    assert await store.list_hits(monitor.id) == []
