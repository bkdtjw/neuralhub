from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.common.logging import get_logger
from backend.config.redis_client import get_redis
from backend.config.settings import settings

logger = get_logger(component="x_budget")

_GATE_KEY = "x:budget:gate"
_CALLS_KEY_PREFIX = "x:budget:calls:"
_DAY_TTL_SECONDS = 90000  # 略大于一天，跨日自动过期重置


class XBudgetError(Exception):
    """X 调用额度闸门拒绝：限速（transient）或日额度耗尽（当天硬性）。"""

    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(reason)


@dataclass
class _BudgetConfig:
    min_interval_seconds: float
    daily_budget: int


async def acquire_x_call_slot() -> None:
    """打真实 X 之前调用：过"最小间隔 + 日额度"两道闸。

    Redis 不可用则降级放行并告警（与飞书降级同策略），不因基础设施抖动而阻断搜索；
    仅额度/限速命中时抛 XBudgetError。闸门自身异常同样放行（只记日志）。
    """
    redis = get_redis()
    if redis is None:
        logger.warning("x_budget_degraded_open")
        return
    cfg = _BudgetConfig(
        settings.x_call_min_interval_seconds,
        settings.x_daily_call_budget,
    )
    try:
        await _check_min_interval(redis, cfg)
        await _check_daily_budget(redis, cfg)
    except XBudgetError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("x_budget_check_failed", error=str(exc))


async def _check_min_interval(redis: Any, cfg: _BudgetConfig) -> None:
    if cfg.min_interval_seconds <= 0:
        return
    stamp = datetime.now(UTC).isoformat()
    px = max(int(cfg.min_interval_seconds * 1000), 1)
    acquired = await redis.set(_GATE_KEY, stamp, nx=True, px=px)
    if not acquired:
        raise XBudgetError(
            "X 搜索调用过于频繁，请稍后重试",
            max(int(cfg.min_interval_seconds), 1),
        )


async def _check_daily_budget(redis: Any, cfg: _BudgetConfig) -> None:
    key = f"{_CALLS_KEY_PREFIX}{datetime.now(UTC).date().isoformat()}"
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, _DAY_TTL_SECONDS)
    if count > cfg.daily_budget:
        raise XBudgetError("今日 X 搜索额度已用尽，请明天再试", 3600)


__all__ = ["XBudgetError", "acquire_x_call_slot"]
