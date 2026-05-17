from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SiteConfig
from backend.core.s02_tools.builtin.feishu_cards import build_health_check_card
from backend.core.s07_task_system.probe_runner import ProbeResult, run_all_probes
from backend.storage.login_workflow_store import LoginWorkflowStore
from backend.storage.run_trace_store import RunTrace, RunTraceStore
from backend.storage.storage_state_store import StorageStateStore

from .site_loader import load_site_configs

logger = get_logger(component="health_check_task")


class HealthCheckConfig(BaseModel):
    user_ids: list[str]
    chat_id: str
    config_dir: Path = Path("config/sites")
    task_id: str = "morning_health_check"
    verbose: bool = False


class HealthCheckDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feishu_client: Any = None
    trace_store: RunTraceStore | None = None
    workflow_store: LoginWorkflowStore | None = None
    state_store: StorageStateStore | None = None
    site_configs: list[SiteConfig] | None = None


async def run_health_check(
    config: HealthCheckConfig,
    deps: HealthCheckDeps | None = None,
) -> dict[str, Any]:
    resolved = deps or HealthCheckDeps()
    trace_store = resolved.trace_store or RunTraceStore()
    started = datetime.now()
    try:
        site_configs = resolved.site_configs or load_site_configs(config.config_dir)
        results: list[ProbeResult] = []
        for user_id in config.user_ids:
            results.extend(
                await run_all_probes(
                    user_id,
                    site_configs,
                    trace_store,
                    resolved.workflow_store,
                    resolved.state_store,
                )
            )
        expired = [result for result in results if not result.ok]
        should_send = bool(resolved.feishu_client) and bool(config.chat_id) and (
            bool(expired) or config.verbose
        )
        if should_send:
            await resolved.feishu_client.send_card(
                config.chat_id,
                build_health_check_card([item.model_dump(mode="json") for item in results]),
            )
        await _record_task_trace(trace_store, config.task_id, started, True, results)
        return {"success": True, "probed": len(results), "expired": len(expired)}
    except Exception as exc:  # noqa: BLE001
        logger.error("health_check_task_failed", error=str(exc))
        await trace_store.record(
            RunTrace(
                task_id=config.task_id,
                kind="health_check",
                started_at=started,
                ended_at=datetime.now(),
                success=False,
                error_code="HEALTH_CHECK_ERROR",
                payload_json={"error": str(exc)},
            )
        )
        return {"success": False, "probed": 0, "expired": 0, "error": str(exc)}


async def _record_task_trace(
    trace_store: RunTraceStore,
    task_id: str,
    started: datetime,
    success: bool,
    results: list[ProbeResult],
) -> None:
    await trace_store.record(
        RunTrace(
            task_id=task_id,
            kind="health_check",
            started_at=started,
            ended_at=datetime.now(),
            success=success,
            payload_json={"results": [item.model_dump(mode="json") for item in results]},
        )
    )


__all__ = ["HealthCheckConfig", "HealthCheckDeps", "run_health_check"]
