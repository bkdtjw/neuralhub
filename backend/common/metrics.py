from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.config import get_redis
from backend.config.settings import settings

_SECONDS_PER_DAY = 86400
METRIC_NAMES = (
    "llm_calls",
    "llm_errors",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_cached_prompt_tokens",
    "tool_calls",
    "tool_errors",
    "task_triggers",
    "task_successes",
    "task_failures",
    "feishu_messages",
    "feishu_replies",
    "agent_runs",
    "plan_step_results_persisted",
    "plan_step_resumed_from_disk",
)
_collector: MetricsCollector | None = None


class MetricsCollector:
    def __init__(self, redis_client: Any, ttl_days: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = max(ttl_days, 1) * _SECONDS_PER_DAY

    async def increment(self, metric: str, value: int = 1) -> None:
        key = self._key(metric, date.today())
        total = await self._redis.incrby(key, value)
        if int(total) == value:
            await self._redis.expire(key, self._ttl_seconds)

    async def get(self, metric: str, bucket_date: str | None = None) -> int:
        target = date.fromisoformat(bucket_date) if bucket_date else date.today()
        raw = await self._redis.get(self._key(metric, target))
        return int(raw or 0)

    async def get_range(self, metric: str, days: int = 7) -> dict[str, int]:
        today = date.today()
        values: dict[str, int] = {}
        for offset in range(max(days, 1) - 1, -1, -1):
            bucket = today - timedelta(days=offset)
            values[bucket.isoformat()] = await self.get(metric, bucket.isoformat())
        return values

    @staticmethod
    def _key(metric: str, bucket_date: date) -> str:
        return f"metrics:{metric}:{bucket_date.isoformat()}"


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
        await (await get_metrics()).increment(metric, value)
    except Exception:
        return


__all__ = ["METRIC_NAMES", "MetricsCollector", "close_metrics", "get_metrics", "incr", "init_metrics"]
