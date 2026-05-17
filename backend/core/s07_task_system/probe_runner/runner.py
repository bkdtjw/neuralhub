from __future__ import annotations

import time
from datetime import datetime

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SiteConfig, load_url
from backend.storage.login_workflow_store import (
    LoginStatus,
    LoginWorkflowStore,
    SiteLoginState,
)
from backend.storage.run_trace_store import RunTrace, RunTraceStore
from backend.storage.storage_state_store import StorageStateStore

from .models import ProbeResult

logger = get_logger(component="probe_runner")


async def run_probe(
    user_id: str,
    site_config: SiteConfig,
    trace_store: RunTraceStore | None = None,
    workflow_store: LoginWorkflowStore | None = None,
    state_store: StorageStateStore | None = None,
) -> ProbeResult:
    started = datetime.now()
    perf = time.monotonic()
    trace = trace_store or RunTraceStore()
    workflow = workflow_store or LoginWorkflowStore()
    state = state_store or StorageStateStore()
    site_id = _site_id(site_config)
    url = _probe_url(site_config)
    try:
        if not _is_state_fresh(user_id, site_config, state):
            return await _finish(
                trace,
                workflow,
                _result(site_id, user_id, False, "stale", perf),
                started,
                url,
            )
        page = await load_url(url, site_config.model_copy(update={"user_id": user_id}))
        ok = not page.login_required
        detail = "ok" if ok else "login_required"
        result = _result(site_id, user_id, ok, detail, perf)
        return await _finish(trace, workflow, result, started, url)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("probe_failed", site_id=site_id, user_id=user_id, error=str(exc))
        result = _result(site_id, user_id, False, "probe_error", perf)
        await trace.record(
            RunTrace(
                task_id=f"probe:{user_id}",
                kind="probe",
                url=url,
                started_at=started,
                ended_at=datetime.now(),
                success=False,
                error_code="PROBE_ERROR",
                payload_json={"site_id": site_id, "error": str(exc)},
            )
        )
        return result


async def run_all_probes(
    user_id: str,
    site_configs: list[SiteConfig],
    trace_store: RunTraceStore | None = None,
    workflow_store: LoginWorkflowStore | None = None,
    state_store: StorageStateStore | None = None,
) -> list[ProbeResult]:
    try:
        results: list[ProbeResult] = []
        for config in site_configs:
            result = await run_probe(user_id, config, trace_store, workflow_store, state_store)
            results.append(result)
        return results
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("probe_all_failed", user_id=user_id, error=str(exc))
        raise AgentError("PROBE_ALL_ERROR", str(exc)) from exc


async def _finish(
    trace: RunTraceStore,
    workflow: LoginWorkflowStore,
    result: ProbeResult,
    started: datetime,
    url: str,
) -> ProbeResult:
    status = LoginStatus.FRESH if result.ok else LoginStatus.EXPIRED
    now = result.checked_at
    await trace.record(
        RunTrace(
            task_id=f"probe:{result.user_id}",
            kind="probe",
            url=url,
            started_at=started,
            ended_at=now,
            success=result.ok,
            error_code="" if result.ok else result.detail.upper(),
            payload_json=result.model_dump(mode="json"),
        )
    )
    await workflow.upsert(
        SiteLoginState(
            site_id=result.site_id,
            user_id=result.user_id,
            status=status,
            last_check_at=now,
            last_fresh_at=now if result.ok else None,
            payload_json={"detail": result.detail, "latency_ms": result.latency_ms},
        )
    )
    return result


def _is_state_fresh(user_id: str, config: SiteConfig, store: StorageStateStore) -> bool:
    if config.storage_state_path is not None:
        path = config.storage_state_path
        return path.exists() and time.time() - path.stat().st_mtime <= store.ttl_seconds
    return bool(config.domain and store.is_state_fresh(user_id, config.domain))


def _result(site_id: str, user_id: str, ok: bool, detail: str, started_perf: float) -> ProbeResult:
    return ProbeResult(
        site_id=site_id,
        user_id=user_id,
        ok=ok,
        detail=detail,
        latency_ms=int((time.monotonic() - started_perf) * 1000),
    )


def _site_id(config: SiteConfig) -> str:
    return config.name or config.domain or "unknown"


def _probe_url(config: SiteConfig) -> str:
    if config.probe_url:
        return config.probe_url
    if config.entry_url:
        return config.entry_url
    return f"https://{config.domain}" if config.domain else ""


__all__ = ["run_all_probes", "run_probe"]
