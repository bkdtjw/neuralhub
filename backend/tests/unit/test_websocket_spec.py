from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes import websocket_runtime
from backend.api.routes.websocket_runtime import CreateLoopInput, create_loop
from backend.api.routes.websocket_support import (
    LoopSettings,
    event_to_ws_message,
    parse_loop_settings,
    resolve_loop_settings,
)
from backend.common.types import AgentEvent

websocket_runtime.CreateLoopInput.model_rebuild(
    _types_namespace={"AgentRuntime": object, "SpecRegistry": object}
)


def test_parse_loop_settings_allows_spec_id_without_model() -> None:
    settings = parse_loop_settings({"type": "run", "spec_id": "code-reviewer"})

    assert settings.spec_id == "code-reviewer"
    assert settings.model == ""


def test_parse_loop_settings_with_mode() -> None:
    settings = parse_loop_settings({"model": "test", "mode": "plan_execute"})

    assert settings.mode == "plan_execute"


def test_parse_loop_settings_default_mode() -> None:
    settings = parse_loop_settings({"model": "test"})

    assert settings.mode == "direct"


@pytest.mark.asyncio
async def test_resolve_loop_settings_skips_provider_lookup_for_spec_id() -> None:
    provider_manager = AsyncMock()
    settings = await resolve_loop_settings(
        LoopSettings(spec_id="code-reviewer", workspace="/workspace"),
        provider_manager,
    )

    assert settings.spec_id == "code-reviewer"
    provider_manager.get_default.assert_not_called()


@pytest.mark.asyncio
async def test_create_loop_uses_agent_runtime_when_spec_id_present() -> None:
    loop = MagicMock()
    loop._config = SimpleNamespace(system_prompt="sys")
    loop.on = MagicMock()
    runtime = AsyncMock()
    runtime.create_loop_from_id = AsyncMock(return_value=loop)

    result = await create_loop(
        CreateLoopInput.model_construct(
            session_id="session-1",
            settings=LoopSettings(spec_id="code-reviewer"),
            agent_runtime=runtime,
            event_sender=AsyncMock(),
        )
    )

    assert result is loop
    runtime.create_loop_from_id.assert_called_once()
    call_kwargs = runtime.create_loop_from_id.call_args.kwargs
    assert call_kwargs["workspace"] == ""
    assert call_kwargs["session_id"] == "session-1"
    assert call_kwargs["model"] == ""
    assert call_kwargs["provider"] == ""
    assert call_kwargs["task_queue"] is None
    assert callable(call_kwargs["event_handler"])
    loop.on.assert_called_once()


def test_event_to_ws_message_supports_sub_agent_events() -> None:
    payload = event_to_ws_message(
        AgentEvent(
            type="sub_agent_completed",
            data={
                "task_id": "task-1",
                "spec_id": "code-reviewer",
                "completed": 1,
                "total": 3,
                "message": "子 agent code-reviewer 已完成（1/3）",
            },
        )
    )

    assert payload["type"] == "sub_agent_completed"
    assert payload["completed"] == 1
    assert payload["total"] == 3


def test_event_to_ws_message_plan_created() -> None:
    payload = event_to_ws_message(
        AgentEvent(type="plan_created", data={"plan_name": "x", "goal": "g", "steps": []})
    )

    assert payload["type"] == "plan_created"
    assert payload["plan_name"] == "x"


def test_event_to_ws_message_plan_step_update() -> None:
    payload = event_to_ws_message(
        AgentEvent(
            type="plan_step_done",
            data={"step_id": 1, "title": "s", "duration_s": 2.0, "output_summary": "ok"},
        )
    )

    assert payload["type"] == "plan_step_update"
    assert payload["status"] == "done"
