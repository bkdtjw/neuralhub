from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .assess import HookVerdict
from .models import HookSignal, HookState, TimelineEntry

TEXT_DUPLICATE_RATIO = 0.84
TIMESTAMP_DUPLICATE_RATIO = 0.62
# 推送门槛的兜底默认值，与 EventHook.materiality 的模型默认（60）对齐。
# 实际路径由 runner 传入 hook.materiality，用户配置值优先，此常量仅在未显式传参时生效。
IMPORTANT_MATERIALITY = 60
_TWEET_RE = re.compile(r"/status(?:es)?/(\d+)")


def dedupe_signals(signals: list[HookSignal]) -> list[HookSignal]:
    result: list[HookSignal] = []
    seen: set[str] = set()
    for signal in signals:
        key = _signal_key(signal)
        if key and key in seen:
            continue
        if any(_same_signal(signal, item) for item in result):
            continue
        result.append(signal)
        if key:
            seen.add(key)
    return result


def filter_known_signals(
    signals: list[HookSignal],
    state: HookState | None,
) -> list[HookSignal]:
    if state is None or not state.timeline:
        return signals
    return [
        signal for signal in signals
        if not any(_same_signal_entry(signal, entry) for entry in state.timeline)
    ]


def visible_verdict(
    verdict: HookVerdict,
    state: HookState | None,
    threshold: int = IMPORTANT_MATERIALITY,
) -> HookVerdict:
    visible = verdict.materiality >= threshold
    entries = filter_new_entries(verdict.new_entries, state) if visible else []
    if entries:
        status = "resolved" if verdict.status == "resolved" else "escalating"
        return verdict.model_copy(
            update={"decision": "push", "status": status, "new_entries": entries},
            deep=True,
        )
    # 无越过门槛的新条目：drop。resolved（收尾场景）不要求新条目达门槛，保留 assess 的 resolved
    # 以便状态机推进到收尾；其余压平为 stable，防止 LLM 随口的 escalating/developing 在无实质进展时抖动。
    status = "resolved" if verdict.status == "resolved" else "stable"
    return verdict.model_copy(
        update={"decision": "drop", "status": status, "new_entries": []},
        deep=True,
    )


def filter_new_entries(
    entries: list[TimelineEntry],
    state: HookState | None,
) -> list[TimelineEntry]:
    result: list[TimelineEntry] = []
    existing = state.timeline if state else []
    for entry in entries:
        if any(_same_entry(entry, item) for item in existing):
            continue
        if any(_same_entry(entry, item) for item in result):
            continue
        result.append(entry)
    return result


def compact_state(state: HookState) -> HookState:
    timeline = filter_new_entries(state.timeline, None)
    if len(timeline) == len(state.timeline):
        return state
    return state.model_copy(
        update={"timeline": timeline, "unseen_count": min(state.unseen_count, len(timeline))},
        deep=True,
    )


def _signal_key(signal: HookSignal) -> str:
    url_key = _url_key(signal.url)
    if url_key:
        return url_key
    text = _normalize_text(signal.text)
    return f"text:{signal.source.lower()}:{signal.ts[:16]}:{text}" if text else ""


def _url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return ""
    match = _TWEET_RE.search(parsed.path)
    if match:
        return f"tweet:{match.group(1)}"
    path = parsed.path.rstrip("/").lower()
    return f"url:{parsed.netloc.lower()}{path}"


def _same_signal(first: HookSignal, second: HookSignal) -> bool:
    return _text_match(first.text, second.text, first.ts, second.ts, first.source, second.source)


def _same_signal_entry(signal: HookSignal, entry: TimelineEntry) -> bool:
    return _text_match(signal.text, entry.text, signal.ts, entry.ts, signal.source, entry.source)


def _same_entry(first: TimelineEntry, second: TimelineEntry) -> bool:
    return _text_match(first.text, second.text, first.ts, second.ts, first.source, second.source)


def _text_match(
    first_text: str,
    second_text: str,
    first_ts: str,
    second_ts: str,
    first_source: str,
    second_source: str,
) -> bool:
    first = _normalize_text(first_text)
    second = _normalize_text(second_text)
    if not first or not second:
        return False
    if first == second:
        return True
    if _numbers(first_text) != _numbers(second_text):
        return False
    ratio = SequenceMatcher(None, first, second).ratio()
    if _same_minute(first_ts, second_ts):
        return ratio >= TIMESTAMP_DUPLICATE_RATIO
    if first_source and first_source == second_source:
        return ratio >= TEXT_DUPLICATE_RATIO
    return ratio >= 0.92


def _same_minute(first_ts: str, second_ts: str) -> bool:
    return bool(first_ts and second_ts and first_ts[:16] == second_ts[:16])


def _normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.lower())


def _numbers(value: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", value)


__all__ = [
    "IMPORTANT_MATERIALITY",
    "compact_state",
    "dedupe_signals",
    "filter_known_signals",
    "filter_new_entries",
    "visible_verdict",
]
