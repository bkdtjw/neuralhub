from __future__ import annotations

import pytest

from backend.common.metrics import (
    METRIC_NAMES,
    bucket_today,
    close_metrics,
    get_metrics,
    incr,
    init_metrics,
    record_latency_sample,
)

from backend.config.settings import settings

from .redis_test_support import use_fake_redis


@pytest.mark.asyncio
async def test_increment_sets_value_and_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = await use_fake_redis(monkeypatch)
    close_metrics()
    await init_metrics()
    await incr("llm_calls")
    key = f"metrics:llm_calls:{bucket_today().isoformat()}"
    assert fake.client.values[key] == "1"
    assert await fake.client.ttl(key) == settings.metrics_ttl_days * 86400


@pytest.mark.asyncio
async def test_get_range_returns_recent_values(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)
    close_metrics()
    await init_metrics()
    collector = await get_metrics()
    await collector.increment("agent_runs", 2)
    values = await collector.get_range("agent_runs", days=2)
    assert values[bucket_today().isoformat()] == 2
    assert len(values) == 2


@pytest.mark.asyncio
async def test_incr_swallows_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = await use_fake_redis(monkeypatch)
    close_metrics()
    await init_metrics()
    fake.client.fail_operations.add("incrby")
    await incr("tool_calls")


@pytest.mark.asyncio
async def test_latency_summary_uses_redis_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = await use_fake_redis(monkeypatch)
    close_metrics()
    await init_metrics()

    await record_latency_sample("tool_call", 100)
    await record_latency_sample("tool_call", 300)
    summary = await (await get_metrics()).get_latency_summary(days=1)

    key = f"metrics:latency:tool_call:{bucket_today().isoformat()}"
    assert await fake.client.ttl(key) == settings.metrics_ttl_days * 86400
    assert summary["tool_call"]["count"] == 2
    assert summary["tool_call"]["p95_ms"] == 300
    assert "sub_agent_task" not in summary


def test_multi_agent_metric_names_are_registered() -> None:
    assert "sub_agent_reuses" in METRIC_NAMES
    assert "sub_agent_wait_detached" in METRIC_NAMES
    assert "sub_agent_result_repaired" in METRIC_NAMES
