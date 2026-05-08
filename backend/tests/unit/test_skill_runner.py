from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    ProviderConfig,
    ProviderType,
    StreamChunk,
    ToolResult,
)
from backend.config.settings import settings
from backend.core.s01_agent_loop import (
    AgentLoop,
    PlanExecuteRunner,
    PlanStep,
    SilentPlanRenderer,
    TodoStep,
)
from backend.core.s02_tools import ToolRegistry
from backend.core.s05_skills import (
    AgentRuntime,
    AgentRuntimeDeps,
    AgentSpec,
    SkillLoader,
    SpecRegistry,
    ToolConfig,
)


class FakeAdapter(LLMAdapter):
    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="done")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


class FakeProviderManager:
    def __init__(self) -> None:
        self.provider = ProviderConfig(
            id="provider-1",
            name="default",
            provider_type=ProviderType.ANTHROPIC,
            base_url="https://example.com",
            api_key="",
            default_model="provider-model",
            available_models=["provider-model"],
            is_default=True,
        )
        self.adapter = FakeAdapter()

    async def list_all(self) -> list[ProviderConfig]:
        return [self.provider]

    async def get_default(self) -> ProviderConfig:
        return self.provider

    async def get_adapter(self, provider_id: str | None = None) -> FakeAdapter:
        return self.adapter


class FakeBridge:
    def __init__(self, manager: object, registry: ToolRegistry) -> None:
        self._registry = registry

    async def sync_all(self) -> int:
        return 0

    async def sync_servers(self, server_ids: set[str]) -> int:
        return len(server_ids)

    def needs_sync(self) -> bool:
        return False


def _register_builtin_tools(registry: ToolRegistry, *_args: object, **_kwargs: object) -> None:
    async def execute(_args: dict[str, object]) -> ToolResult:
        return ToolResult(output="ok")

    from backend.common.types import ToolDefinition, ToolParameterSchema

    for name in ("Read", "Bash", "Write"):
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                category="code-analysis",
                parameters=ToolParameterSchema(),
            ),
            execute,
        )


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> AgentRuntime:
    monkeypatch.setattr(
        "backend.core.s05_skills.runtime.register_builtin_tools", _register_builtin_tools
    )
    monkeypatch.setattr("backend.core.s05_skills.runtime.MCPToolBridge", FakeBridge)
    monkeypatch.setattr(
        "backend.core.s05_skills.runtime.build_system_prompt", lambda workspace: f"base:{workspace}"
    )
    return AgentRuntime(
        AgentRuntimeDeps.model_construct(
            provider_manager=FakeProviderManager(),
            mcp_manager=object(),
            settings=settings,
            spec_registry=SpecRegistry(),
        )
    )


def test_agent_spec_mode_defaults_and_validation() -> None:
    spec = AgentSpec(id="test", title="test", category="coding")
    assert spec.default_mode == "direct"
    assert set(spec.allow_modes) == {"direct", "plan_execute"}
    with pytest.raises(ValidationError):
        AgentSpec(
            id="bad",
            title="bad",
            category="coding",
            default_mode="plan_execute",
            allow_modes=["direct"],
        )
    plan_only = AgentSpec(
        id="plan",
        title="plan",
        category="coding",
        default_mode="plan_execute",
        allow_modes=["plan_execute"],
    )
    assert plan_only.default_mode == "plan_execute"


def test_skill_loader_parses_mode_fields(tmp_path: Path) -> None:
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: test-skill\n"
        "title: Test\n"
        "category: coding\n"
        "default_mode: plan_execute\n"
        "allow_modes: [plan_execute]\n"
        "---\n"
        "Body",
        encoding="utf-8",
    )
    spec = SkillLoader(str(tmp_path)).load_one(skill_dir)
    assert spec is not None
    assert spec.default_mode == "plan_execute"
    assert spec.allow_modes == ["plan_execute"]


@pytest.mark.asyncio
async def test_create_runner_modes_and_validation(runtime: AgentRuntime) -> None:
    plan_spec = AgentSpec(
        id="planner", title="Planner", category="coding", default_mode="plan_execute"
    )
    direct = await runtime.create_runner(spec=plan_spec, mode="direct", workspace="workspace")
    plan = await runtime.create_runner(spec=plan_spec, workspace="workspace")
    assert isinstance(direct, AgentLoop)
    assert isinstance(plan, PlanExecuteRunner)
    with pytest.raises(AgentError, match="MODE_NOT_ALLOWED"):
        await runtime.create_runner(
            spec=AgentSpec(
                id="direct-only", title="Direct", category="coding", allow_modes=["direct"]
            ),
            mode="plan_execute",
        )


@pytest.mark.asyncio
async def test_create_runner_from_spec_id_and_silent_renderer(runtime: AgentRuntime) -> None:
    spec = AgentSpec(
        id="daily-ai-news", title="Daily", category="aggregation", default_mode="plan_execute"
    )
    runtime._deps.spec_registry.register(spec)  # noqa: SLF001
    runner = await runtime.create_runner(spec_id="daily-ai-news")
    assert isinstance(runner, PlanExecuteRunner)
    assert isinstance(runner._renderer, SilentPlanRenderer)  # noqa: SLF001


@pytest.mark.asyncio
async def test_plan_runner_uses_spec_tools_and_prompt(runtime: AgentRuntime) -> None:
    spec = AgentSpec(
        id="researcher",
        title="Researcher",
        category="research",
        system_prompt="spec prompt",
        tools=ToolConfig(allowed_tools=["Read", "Bash"]),
        max_iterations=7,
    )
    runner = await runtime.create_runner(spec=spec, mode="plan_execute", workspace="workspace")
    assert isinstance(runner, PlanExecuteRunner)
    names = sorted(tool.name for tool in runner._tool_registry.list_definitions())  # noqa: SLF001
    assert names == ["Bash", "Read"]
    context = type(
        "StepContext",
        (),
        {
            "plan_step": PlanStep(step_id=1, title="t", description="d"),
            "step_index": 1,
            "total_steps": 1,
            "previous_summary": "",
        },
    )()
    system_prompt, _ = runner._build_step_prompt(context)  # noqa: SLF001
    loop = runner._build_step_loop(TodoStep(id=1, title="t"), context)  # noqa: SLF001
    assert "spec prompt" in system_prompt
    assert "base:" in system_prompt
    assert loop._config.max_iterations == 7  # noqa: SLF001
