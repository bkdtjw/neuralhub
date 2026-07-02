from __future__ import annotations

from datetime import UTC, datetime

from .assess import HookVerdict
from .models import HookState, SourceHealth

CADENCE_ESCALATING = 8
CADENCE_STABLE = 180
CADENCE_RESOLVED = 0
PUSH_COOLDOWN_MINUTES = 30


def adaptive_cadence(status: str, base_minutes: int) -> int:
    if status == "resolved":
        return CADENCE_RESOLVED
    # escalating（局势升级）提频：取用户 base 与 CADENCE_ESCALATING 的较小值，
    # 既加密扫描又不会比用户配置更慢。其余状态沿用用户 base。
    if status == "escalating":
        return min(base_minutes, CADENCE_ESCALATING)
    return base_minutes


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def next_state(
    hook_id: str,
    prev_state: HookState | None,
    current_state: HookState | None,
    verdict: HookVerdict,
    now: str,
    scanned_sources: list[tuple[str, bool]],
) -> HookState:
    base = current_state or prev_state or HookState(hook_id=hook_id)
    prev_summary = prev_state.summary if prev_state else ""
    return base.model_copy(
        update={
            "hook_id": hook_id,
            "confidence": verdict.turning_score,
            "status": verdict.status,
            "summary": verdict.summary or prev_summary or "尚未扫描",
            "source_health": scan_health(scanned_sources, base.source_health, now),
            "last_scanned": now,
        },
        deep=True,
    )


def scan_health(
    scanned_sources: list[tuple[str, bool]],
    health: list[SourceHealth],
    now: str,
) -> list[SourceHealth]:
    # 只标记本轮真正扫过的源；关闭的源不能被标成"正常"。
    # ok=False（源故障）时只翻 online 状态，不写 last_ok，保持"last_ok=最后一次成功时间"语义。
    updated = [item.model_copy(deep=True) for item in health]
    for source, ok in scanned_sources:
        updated = _mark_health(updated, source, ok, now)
    return updated


def _mark_health(
    health: list[SourceHealth],
    source: str,
    online: bool,
    now: str,
) -> list[SourceHealth]:
    updated: list[SourceHealth] = []
    found = False
    for item in health:
        if item.source == source:
            found = True
            updated.append(item.model_copy(update=_health_update(online, now), deep=True))
        else:
            updated.append(item.model_copy(deep=True))
    if not found:
        updated.append(SourceHealth(source=source, **_health_update(online, now)))
    return updated


def _health_update(online: bool, now: str) -> dict[str, str | bool]:
    update: dict[str, str | bool] = {"online": online}
    if online:
        update["last_ok"] = now
    return update


def should_push(
    verdict: HookVerdict,
    prev_state: HookState | None,
    now: str,
) -> bool:
    if verdict.decision != "push":
        return False
    last_pushed = prev_state.last_pushed_ts if prev_state else ""
    return _minutes_since(last_pushed, now) >= PUSH_COOLDOWN_MINUTES


def _minutes_since(last_iso: str, now_iso: str) -> float:
    try:
        return (_parse_iso(now_iso) - _parse_iso(last_iso)).total_seconds() / 60
    except Exception:
        return 1_000_000_000


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "CADENCE_ESCALATING",
    "CADENCE_RESOLVED",
    "CADENCE_STABLE",
    "PUSH_COOLDOWN_MINUTES",
    "adaptive_cadence",
    "next_state",
    "scan_health",
    "should_push",
    "utc_now",
]
