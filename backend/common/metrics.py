from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import get_redis
from backend.config.settings import settings
from backend.common.prometheus_metrics import record_business_metric


def bucket_today() -> date:
    # 指标按业务时区分桶：容器多为 UTC，直接 date.today() 会把北京 0-8 点的量记进前一天
    tz_name = getattr(settings, "metrics_timezone", "")
    if not tz_name:
        return date.today()
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001
        return date.today()

_SECONDS_PER_DAY = 86400
_MAX_LATENCY_SAMPLES_PER_DAY = 2000
METRIC_NAMES = (
    "llm_calls",
    "llm_errors",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_cached_prompt_tokens",
    "llm_cache_creation_tokens",
    "tool_calls",
    "tool_errors",
    "task_triggers",
    "task_successes",
    "task_failures",
    "feishu_messages",
    "feishu_replies",
    "feishu_dedup_failures",
    "agent_runs",
    "plan_step_results_persisted",
    "plan_step_resumed_from_disk",
    "sub_agent_final_reviews",
    "sub_agent_reuses",
    "sub_agent_result_fallbacks",
    "sub_agent_result_parsed",
    "sub_agent_result_repaired",
    "sub_agent_tasks_submitted",
    "sub_agent_wait_detached",
    "sub_agent_wait_failures",
)
LATENCY_METRICS = {
    "http": "HTTP 请求",
    "agent_run": "Agent 执行",
    "llm_request": "LLM 请求",
    "tool_call": "工具调用",
    "sub_agent_task": "子 Agent",
}
_collector: MetricsCollector | None = None


class MetricsCollector:
    def __init__(self, redis_client: Any, ttl_days: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = max(ttl_days, 1) * _SECONDS_PER_DAY

    async def increment(self, metric: str, value: int = 1) -> None:
        key = self._key(metric, bucket_today())
        total = await self._redis.incrby(key, value)
        if int(total) == value:
            await self._redis.expire(key, self._ttl_seconds)

    async def get(self, metric: str, bucket_date: str | None = None) -> int:
        target = date.fromisoformat(bucket_date) if bucket_date else bucket_today()
        raw = await self._redis.get(self._key(metric, target))
        return int(raw or 0)

    async def get_range(self, metric: str, days: int = 7) -> dict[str, int]:
        today = bucket_today()
        values: dict[str, int] = {}
        for offset in range(max(days, 1) - 1, -1, -1):
            bucket = today - timedelta(days=offset)
            values[bucket.isoformat()] = await self.get(metric, bucket.isoformat())
        return values

    async def record_latency(self, metric: str, duration_ms: float) -> None:
        if metric not in LATENCY_METRICS or duration_ms < 0:
            return
        key = self._latency_key(metric, bucket_today())
        total = await self._redis.lpush(key, str(round(duration_ms, 2)))
        if int(total) == 1:
            await self._redis.expire(key, self._ttl_seconds)
        await self._redis.ltrim(key, 0, _MAX_LATENCY_SAMPLES_PER_DAY - 1)

    async def get_latency_summary(self, days: int = 1) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for metric, name in LATENCY_METRICS.items():
            samples = await self._latency_samples(metric, days)
            if samples:
                summary[metric] = _latency_stats(name, samples)
        return summary

    async def _latency_samples(self, metric: str, days: int) -> list[float]:
        today = bucket_today()
        samples: list[float] = []
        for offset in range(max(days, 1) - 1, -1, -1):
            bucket = today - timedelta(days=offset)
            raw_values = await self._redis.lrange(self._latency_key(metric, bucket), 0, -1)
            for raw in raw_values:
                try:
                    samples.append(float(raw))
                except (TypeError, ValueError):
                    continue
        return samples

    @staticmethod
    def _key(metric: str, bucket_date: date) -> str:
        return f"metrics:{metric}:{bucket_date.isoformat()}"

    @staticmethod
    def _latency_key(metric: str, bucket_date: date) -> str:
        return f"metrics:latency:{metric}:{bucket_date.isoformat()}"


async def init_metrics() -> None:
    global _collector
    redis = get_redis()
    if redis is not None:
        _collector = MetricsCollector(redis, settings.metrics_ttl_days)


def close_metrics() -> None:
    global _collector
    _collector = None


async def get_metrics() -> MetricsCollector:
    global _collector
    redis = get_redis()
    if redis is None:
        raise RuntimeError("Redis client is not initialized.")
    if _collector is None or getattr(_collector, "_redis", None) is not redis:
        _collector = MetricsCollector(redis, settings.metrics_ttl_days)
    return _collector


async def incr(metric: str, value: int = 1) -> None:
    try:
        record_business_metric(metric, value)
    except Exception:
        pass
    try:
        await (await get_metrics()).increment(metric, value)
    except Exception:
        return


async def record_latency_sample(metric: str, duration_ms: float) -> None:
    try:
        await (await get_metrics()).record_latency(metric, duration_ms)
    except Exception:
        return


def record_latency_sample_nowait(metric: str, duration_ms: float) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(record_latency_sample(metric, duration_ms))


def _latency_stats(name: str, samples: list[float]) -> dict[str, Any]:
    items = sorted(samples)
    return {
        "name": name,
        "count": len(items),
        "p50_ms": _percentile(items, 50),
        "p95_ms": _percentile(items, 95),
        "max_ms": round(items[-1], 2),
    }


def _percentile(items: list[float], percentile: int) -> float:
    index = max(math.ceil((percentile / 100) * len(items)) - 1, 0)
    return round(items[index], 2)


__all__ = [
    "LATENCY_METRICS",
    "METRIC_NAMES",
    "MetricsCollector",
    "close_metrics",
    "get_metrics",
    "incr",
    "init_metrics",
    "record_latency_sample",
    "record_latency_sample_nowait",
]
