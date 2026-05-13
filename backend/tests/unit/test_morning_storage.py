from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.core.s02_tools.builtin.article_extractor import Article
from backend.storage.asset_store import AssetStore
from backend.storage.login_workflow_store import (
    LoginStatus,
    LoginWorkflowStore,
    SiteLoginState,
)
from backend.storage.run_trace_store import RunTrace, RunTraceStore


@pytest.mark.asyncio
async def test_asset_store_saves_artifacts(tmp_path: Path) -> None:
    store = AssetStore(root=tmp_path)
    shot = await store.save_screenshot("task1", "https://example.com/a", b"png")
    article = await store.save_article(
        "task1",
        Article(url="https://example.com/a", title="Title", body="Body"),
    )
    report = await store.save_report("task1", "# report")
    assert shot.read_bytes() == b"png"
    assert article.read_text(encoding="utf-8")
    assert report.read_text(encoding="utf-8") == "# report"


@pytest.mark.asyncio
async def test_run_trace_store_records_and_queries(db_session_factory: object) -> None:
    store = RunTraceStore(db_session_factory)
    await store.record(
        RunTrace(task_id="task1", kind="probe", url="https://example.com", success=True)
    )
    rows = await store.query(task_id="task1", kind="probe")
    assert len(rows) == 1
    assert rows[0].success is True


@pytest.mark.asyncio
async def test_login_workflow_store_save_get_and_advance(db_session_factory: object) -> None:
    store = LoginWorkflowStore(db_session_factory)
    await store.upsert(SiteLoginState(site_id="site1", user_id="u1", status=LoginStatus.EXPIRED))
    state = await store.get("u1", "site1")
    assert state is not None
    assert state.status == LoginStatus.EXPIRED

    workflow_id = await store.create_workflow("u1", ["site1", "site2"])
    first = await store.advance(workflow_id)
    assert first is not None
    assert first.site_id == "site1"
    assert first.status == LoginStatus.IN_PROGRESS
    await store.upsert(first.model_copy(update={"status": LoginStatus.FRESH}))
    second = await store.advance(workflow_id)
    assert second is not None
    assert second.site_id == "site2"


@pytest.mark.asyncio
async def test_login_workflow_advance_is_serialized(db_session_factory: object) -> None:
    store = LoginWorkflowStore(db_session_factory)
    workflow_id = await store.create_workflow("u1", ["site1", "site2"])
    first, second = await asyncio.gather(
        store.advance(workflow_id),
        store.advance(workflow_id),
    )
    states = [state for state in (first, second) if state is not None]
    in_progress = await store.list_by_status("u1", [LoginStatus.IN_PROGRESS])
    assert states
    assert len(states) == 1 or states[0].site_id != states[1].site_id
    assert len(in_progress) == 1
    assert in_progress[0].site_id == "site1"
