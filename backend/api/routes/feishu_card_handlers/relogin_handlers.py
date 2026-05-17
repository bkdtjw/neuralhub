from __future__ import annotations

from datetime import datetime

from backend.core.s02_tools.builtin.browser import SiteConfig
from backend.core.s02_tools.builtin.feishu_cards import build_relogin_card
from backend.core.s07_task_system.probe_runner import run_probe
from backend.storage.login_workflow_store import (
    LoginStatus,
    LoginWorkflowStore,
    SiteLoginState,
)
from backend.storage.run_trace_store import RunTraceStore

from .models import ActionRoute, CardHandlerDeps
from .site_config import load_site_configs, resolve_site_config


async def handle_relogin_start(route: ActionRoute, deps: CardHandlerDeps) -> dict:
    store = LoginWorkflowStore(deps.session_factory)
    expired = await store.list_by_status(route.user_id, [LoginStatus.EXPIRED, LoginStatus.PENDING])
    sites = [state.site_id for state in expired]
    workflow_id = await store.create_workflow(route.user_id, sites)
    current = await store.advance(workflow_id) if sites else None
    if current is not None:
        await _send_relogin_card(current, deps)
    return {"status": "ok", "workflow_id": workflow_id, "site_count": len(sites)}


async def handle_relogin_done(route: ActionRoute, deps: CardHandlerDeps) -> dict:
    store = LoginWorkflowStore(deps.session_factory)
    site = route.target
    config = resolve_site_config(site, deps.config_dir) or SiteConfig(name=site, domain=site)
    result = await run_probe(
        route.user_id,
        config,
        RunTraceStore(deps.session_factory),
        store,
    )
    if not result.ok:
        await store.upsert(
            SiteLoginState(
                site_id=site,
                user_id=route.user_id,
                status=LoginStatus.IN_PROGRESS,
                last_check_at=datetime.now(),
                payload_json={"detail": result.detail},
            )
        )
        return {"status": "probe_failed", "site": site, "detail": result.detail}
    state = await store.get(route.user_id, site)
    next_state = await store.advance(state.workflow_id) if state and state.workflow_id else None
    if next_state is not None:
        await _send_relogin_card(next_state, deps)
    return {"status": "fresh", "site": site, "next_site": next_state.site_id if next_state else ""}


async def handle_skip_site(route: ActionRoute, deps: CardHandlerDeps) -> dict:
    store = LoginWorkflowStore(deps.session_factory)
    state = await store.get(route.user_id, route.target)
    if state is None:
        return {"status": "missing", "site": route.target}
    await store.upsert(state.model_copy(update={"status": LoginStatus.SKIPPED}))
    next_state = await store.advance(state.workflow_id)
    if next_state is not None:
        await _send_relogin_card(next_state, deps)
    return {"status": "skipped", "site": route.target}


async def _send_relogin_card(state: SiteLoginState, deps: CardHandlerDeps) -> None:
    if deps.feishu_client is None or not deps.chat_id:
        return
    await deps.feishu_client.send_card(
        deps.chat_id,
        build_relogin_card(state.site_id, state.current_step, state.total_steps),
    )


__all__ = ["handle_relogin_done", "handle_relogin_start", "handle_skip_site"]
