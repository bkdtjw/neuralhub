from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.s02_tools.builtin.browser import PageResult, SiteConfig
from backend.core.s07_task_system.probe_runner import runner
from backend.core.s07_task_system.tasks.health_check_task import (
    HealthCheckConfig,
    HealthCheckDeps,
    run_health_check,
)
from backend.storage.login_workflow_store import LoginWorkflowStore
from backend.storage.run_trace_store import RunTraceStore
from backend.storage.storage_state_store import StorageStateStore


class FakeFeishuClient:
    def __init__(self) -> None:
        self.cards: list[dict] = []

    async def send_card(self, chat_id: str, card_content: dict) -> str:
        self.cards.append(card_content)
        return "message-id"


@pytest.mark.asyncio
async def test_health_check_sends_card_and_records_probe_trace(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    async def fake_load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
        return PageResult(url=url, html="<html></html>", login_required=True)

    monkeypatch.setattr(runner, "load_url", fake_load_url)
    trace_store = RunTraceStore(db_session_factory)
    client = FakeFeishuClient()
    result = await run_health_check(
        HealthCheckConfig(user_ids=["u1"], chat_id="chat"),
        HealthCheckDeps(
            feishu_client=client,
            trace_store=trace_store,
            workflow_store=LoginWorkflowStore(db_session_factory),
            state_store=StorageStateStore(root=tmp_path),
            site_configs=[
                SiteConfig(
                    name="site1",
                    domain="example.com",
                    storage_state_path=state_path,
                    probe_url="https://example.com/private",
                )
            ],
        ),
    )
    assert result == {"success": True, "probed": 1, "expired": 1}
    assert client.cards
    traces = await trace_store.query(kind="probe")
    assert traces[0].error_code == "LOGIN_REQUIRED"


@pytest.mark.asyncio
async def test_health_check_verbose_sends_all_ok_card(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    async def fake_load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
        return PageResult(url=url, html="<html></html>", login_required=False)

    site_configs = [
        SiteConfig(
            name="site1",
            domain="example.com",
            storage_state_path=state_path,
            probe_url="https://example.com/private",
        )
    ]
    monkeypatch.setattr(runner, "load_url", fake_load_url)
    trace_store = RunTraceStore(db_session_factory)
    quiet_client = FakeFeishuClient()
    await run_health_check(
        HealthCheckConfig(user_ids=["u1"], chat_id="chat"),
        HealthCheckDeps(
            feishu_client=quiet_client,
            trace_store=trace_store,
            workflow_store=LoginWorkflowStore(db_session_factory),
            state_store=StorageStateStore(root=tmp_path),
            site_configs=site_configs,
        ),
    )
    assert quiet_client.cards == []

    verbose_client = FakeFeishuClient()
    result = await run_health_check(
        HealthCheckConfig(user_ids=["u1"], chat_id="chat", verbose=True),
        HealthCheckDeps(
            feishu_client=verbose_client,
            trace_store=trace_store,
            workflow_store=LoginWorkflowStore(db_session_factory),
            state_store=StorageStateStore(root=tmp_path),
            site_configs=site_configs,
        ),
    )
    assert result == {"success": True, "probed": 1, "expired": 0}
    assert len(verbose_client.cards) == 1
