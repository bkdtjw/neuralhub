from __future__ import annotations

from datetime import UTC, datetime

from .models import EventHook, HookSummary, SourceHealth


def normalize_accounts(accounts: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for account in accounts:
        value = account.strip().lstrip("@").strip().lower()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def source_health_for(hook: EventHook) -> list[SourceHealth]:
    enabled = (
        ("twitter", hook.sources.twitter),
        ("exa", hook.sources.exa_web),
        ("zhipu", hook.sources.zhipu_search),
        ("youtube", hook.sources.youtube),
    )
    return [SourceHealth(source=source) for source, is_enabled in enabled if is_enabled]


def parse_seed_item(item: dict[str, object]) -> HookSummary:
    if "hook" in item:
        return HookSummary.model_validate(item)
    return HookSummary(hook=EventHook.model_validate(item), state=None)


def parse_ts(ts: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        try:
            parsed = datetime.strptime(ts, "%a %b %d %H:%M:%S %z %Y")
        except Exception:
            parsed = datetime.min
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "normalize_accounts",
    "parse_seed_item",
    "parse_ts",
    "source_health_for",
    "utc_now",
]
