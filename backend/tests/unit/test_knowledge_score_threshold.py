from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from backend.config.settings import settings
from backend.core.s13_knowledge import KnowledgeService, SearchRequest
from backend.core.s13_knowledge.models import SearchHit


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class _StubEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 2048 for _ in texts]


class _StubStore:
    # 只实现 search 与 KnowledgeService.__init__ 依赖的 _session_factory，不触碰 DB。
    def __init__(self, hits: list[SearchHit]) -> None:
        self._session_factory = None
        self._hits = hits

    async def search(
        self, kb_id: str, query_embedding: list[float], top_k: int
    ) -> list[SearchHit]:
        return list(self._hits)


def _hit(score: float, name: str) -> SearchHit:
    return SearchHit(content=f"chunk-{name}", score=score, document_name=name)


def _service(hits: list[SearchHit]) -> KnowledgeService:
    return KnowledgeService(store=_StubStore(hits), embedder=_StubEmbedder())


@pytest.mark.asyncio
async def test_search_drops_hits_below_threshold_and_keeps_boundary() -> None:
    threshold = settings.knowledge_score_threshold
    hits = [
        _hit(threshold + 0.4, "high"),  # 明显相关 -> 保留
        _hit(threshold, "boundary"),  # 恰好等于阈值 -> 保留（>=）
        _hit(threshold - 0.01, "low"),  # 略低于阈值 -> 丢弃
        _hit(threshold - 0.3, "irrelevant"),  # 明显无关 -> 丢弃
    ]

    result = await _service(hits).search(SearchRequest(query="任意提问", kb_id="kb-1"))

    assert [hit.document_name for hit in result] == ["high", "boundary"]
    assert all(hit.score >= threshold for hit in result)


@pytest.mark.asyncio
async def test_search_returns_empty_when_all_below_threshold() -> None:
    threshold = settings.knowledge_score_threshold
    hits = [
        _hit(threshold - 0.01, "a"),
        _hit(threshold - 0.2, "b"),
        _hit(threshold - 0.5, "c"),
    ]

    result = await _service(hits).search(SearchRequest(query="无关提问", kb_id="kb-1"))

    assert result == []
