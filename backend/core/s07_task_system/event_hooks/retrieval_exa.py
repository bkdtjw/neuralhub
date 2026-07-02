from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel

from backend.common.logging import get_logger

from .models import EventHook, HookSignal, RetrievalOutcome
from .retrieval import HookRetrievalError

EXA_NUM_RESULTS = 6
EXA_DAYS = 14


class ExaHit(Protocol):
    title: str
    url: str
    published_date: str
    author: str
    highlights: list[str]
    text: str


class ExaQuery(BaseModel):
    query: str
    num_results: int = EXA_NUM_RESULTS
    days: int = EXA_DAYS


ExaSearchFn = Callable[[ExaQuery], Awaitable[Sequence[ExaHit]]]


def build_exa_query(hook: EventHook) -> str:
    keywords = [keyword.strip() for keyword in hook.twitter.keywords if keyword.strip()]
    if keywords:
        return " ".join(keywords)
    return hook.name.strip()


async def retrieve_exa(
    hook: EventHook,
    exa_search_fn: ExaSearchFn,
    *,
    days: int = EXA_DAYS,
) -> RetrievalOutcome:
    try:
        query = build_exa_query(hook)
        if not query:
            return RetrievalOutcome(signals=[], ok=True)
        try:
            hits = await exa_search_fn(
                ExaQuery(query=query, num_results=EXA_NUM_RESULTS, days=days)
            )
        except Exception as exc:
            get_logger(component="event_hooks_retrieval_exa").warning(
                "event_hook_retrieval_lane_failed",
                hook_id=hook.id,
                lane="exa:confirm",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
            return RetrievalOutcome(signals=[], ok=False)
        signals = [_signal_from_hit(hit, hook.twitter.keywords) for hit in hits]
        return RetrievalOutcome(signals=signals, ok=True)
    except HookRetrievalError:
        raise
    except Exception as exc:
        raise HookRetrievalError(f"HOOK_RETRIEVAL_ERROR: {exc}") from exc


def _signal_from_hit(hit: ExaHit, keywords: list[str]) -> HookSignal:
    highlight = hit.highlights[0] if hit.highlights else ""
    text = f"{hit.title} — {highlight}".strip()[:280]
    return HookSignal(
        source="exa",
        lane="confirm",
        text=text,
        url=hit.url,
        author=hit.author.strip() or _domain(hit.url),
        ts=hit.published_date,
        engagement=0,
        matched=_matched_keywords(hit, keywords),
    )


def _matched_keywords(hit: ExaHit, keywords: list[str]) -> list[str]:
    haystack = " ".join([hit.title, *hit.highlights, hit.text]).lower()
    matches: list[str] = []
    for keyword in keywords:
        value = keyword.strip()
        if value and value.lower() in haystack and value not in matches:
            matches.append(value)
    return matches


def _domain(url: str) -> str:
    return urlparse(url.strip()).netloc.lower()


__all__ = [
    "EXA_DAYS",
    "EXA_NUM_RESULTS",
    "ExaHit",
    "ExaQuery",
    "ExaSearchFn",
    "build_exa_query",
    "retrieve_exa",
]
