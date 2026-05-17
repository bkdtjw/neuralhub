from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.s02_tools.builtin.browser import PageResult, SiteConfig
from backend.core.s07_task_system.probe_runner import runner
from backend.core.s07_task_system.probe_runner.runner import run_probe
from backend.storage.login_workflow_store import LoginStatus, LoginWorkflowStore
from backend.storage.run_trace_store import RunTraceStore
from backend.storage.storage_state_store import StorageStateStore


@pytest.mark.asyncio
async def test_probe_stale_state_does_not_launch_browser(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
    tmp_path: Path,
) -> None:
    called = False

    async def fail_load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
        nonlocal called
        called = True
        raise AssertionError("browser should not start")

    monkeypatch.setattr(runner, "load_url", fail_load_url)
    trace_store = RunTraceStore(db_session_factory)
    workflow_store = LoginWorkflowStore(db_session_factory)
    result = await run_probe(
        "u1",
        SiteConfig(
            name="site1",
            domain="example.com",
            storage_state_path=tmp_path / "missing.json",
            probe_url="https://example.com/private",
        ),
        trace_store,
        workflow_store,
        StorageStateStore(root=tmp_path),
    )
    assert result.ok is False
    assert result.detail == "stale"
    assert called is False
    assert (await trace_store.query(kind="probe"))[0].error_code == "STALE"
    state = await workflow_store.get("u1", "site1")
    assert state is not None
    assert state.status == LoginStatus.EXPIRED


@pytest.mark.asyncio
async def test_probe_fresh_state_uses_load_url(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")

    async def fake_load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
        return PageResult(url=url, html="<html></html>", login_required=False)

    monkeypatch.setattr(runner, "load_url", fake_load_url)
    result = await run_probe(
        "u1",
        SiteConfig(name="site1", domain="example.com", storage_state_path=state_file),
        RunTraceStore(db_session_factory),
        LoginWorkflowStore(db_session_factory),
        StorageStateStore(root=tmp_path),
    )
    assert result.ok is True
    assert result.detail == "ok"
