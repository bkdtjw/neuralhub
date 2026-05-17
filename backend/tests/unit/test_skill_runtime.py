from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    ProviderConfig,
    ProviderType,
    StreamChunk,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.config.settings import settings
from backend.core.s02_tools import ToolRegistry
from backend.core.s05_skills import (
    AgentCategory,
    AgentRuntime,
    AgentRuntimeDeps,
    AgentSpec,
    SpecRegistry,
    ToolConfig,
    extract_required_mcp_servers,
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
        assert provider_id in {None, self.provider.id}
        return self.adapter


class FakeBridge:
    def __init__(self, manager: object, registry: ToolRegistry) -> None:
        self._registry = registry
        self.sync_all_calls = 0
        self.sync_servers_calls: list[set[str]] = []
        manager.bridge = self

    def needs_sync(self) -> bool:
        return False

    async def sync_all(self) -> int:
        self.sync_all_calls += 1
        self._registry.register(_tool("mcp__demo__lookup"), _executor("mcp"))
        return 1

    async def sync_servers(self, server_ids: set[str]) -> int:
        self.sync_servers_calls.append(set(server_ids))
        if "demo" in server_ids:
            self._registry.register(_tool("mcp__demo__lookup"), _executor("mcp"))
        if "other" in server_ids:
            self._registry.register(_tool("mcp__other__lookup"), _executor("mcp"))
        return len(server_ids)

    async def sync_if_needed(self) -> int:
        return 0


class FakeMCPManager:
    bridge: FakeBridge | None = None


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="code-analysis",
        parameters=ToolParameterSchema(),
    )


def _executor(output: str):
    async def execute(_args: dict[str, object]) -> ToolResult:
        return ToolResult(output=output)

    return execute


def _register_builtin_tools(
    registry: ToolRegistry,
    workspace: str | None,
    mode: str = "auto",
    adapter: LLMAdapter | None = None,
    default_model: str = "",
    agent_runtime: object | None = None,
    spec_registry: object | None = None,
    task_queue: object | None = None,
    event_handler: object | None = None,
    is_sub_agent: bool = False,
    parent_task_id: str = "",
) -> None:
    _ = (
        workspace,
        mode,
        adapter,
        default_model,
        agent_runtime,
        spec_registry,
        task_queue,
        event_handler,
        parent_task_id,
    )
    for name in ("Read", "Bash"):
        registry.register(_tool(name), _executor(name))
    if not is_sub_agent:
        for name in ("dispatch_agent", "orchestrate_agents", "query_specs", "spawn_agent"):
            registry.register(_tool(name), _executor(name))


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> AgentRuntime:
    monkeypatch.setattr(
        "backend.core.s05_skills.runtime.register_builtin_tools",
        _register_builtin_tools,
    )
    monkeypatch.setattr("backend.core.s05_skills.runtime.MCPToolBridge", FakeBridge)
    monkeypatch.setattr(
        "backend.core.s05_skills.runtime.build_system_prompt",
        lambda workspace: f"base:{workspace}",
    )
    registry = SpecRegistry()
    return AgentRuntime(
        AgentRuntimeDeps.model_construct(
            provider_manager=FakeProviderManager(),
            mcp_manager=FakeMCPManager(),
            settings=settings,
            spec_registry=registry,
        )
    )


@pytest.mark.asyncio
async def test_create_loop_from_id_uses_prompt_and_tool_whitelist(runtime: AgentRuntime) -> None:
    spec = AgentSpec(
        id="daily-ai-news",
        title="AI 圈早报",
        category=AgentCategory.AGGREGATION,
        system_prompt="spec prompt",
        tools=ToolConfig(allowed_tools=["Read"]),
    )
    runtime._deps.spec_registry.register(spec)  # noqa: SLF001

    loop = await runtime.create_loop_from_id(
        "daily-ai-news",
        workspace="workspace",
        session_id="sess-1",
    )

    assert loop._config.model == "provider-model"  # noqa: SLF001
    assert loop._config.provider == "provider-1"  # noqa: SLF001
    assert "base:" in loop._config.system_prompt  # noqa: SLF001
    assert "spec prompt" not in loop._config.system_prompt  # noqa: SLF001
    assert loop._static_skill_messages[0].content == "spec prompt"  # noqa: SLF001
    assert sorted(tool.name for tool in loop._executor.list_definitions()) == ["Read"]  # noqa: SLF001
    bridge = runtime._deps.mcp_manager.bridge  # noqa: SLF001
    assert bridge is not None
    assert bridge.sync_all_calls == 0
    assert bridge.sync_servers_calls == []


@pytest.mark.asyncio
async def test_create_loop_syncs_only_required_mcp_servers(runtime: AgentRuntime) -> None:
    spec = AgentSpec(
        id="mcp-skill",
        title="MCP Skill",
        category=AgentCategory.ASSISTANT,
        system_prompt="mcp",
        tools=ToolConfig(allowed_tools=["Read", "mcp__demo__lookup"]),
    )

    loop = await runtime.create_loop(spec, workspace="workspace")

    assert sorted(tool.name for tool in loop._executor.list_definitions()) == [  # noqa: SLF001
        "Read",
        "mcp__demo__lookup",
    ]
    bridge = runtime._deps.mcp_manager.bridge  # noqa: SLF001
    assert bridge is not None
    assert bridge.sync_all_calls == 0
    assert bridge.sync_servers_calls == [{"demo"}]


def test_extract_required_mcp_servers_from_allowed_tools() -> None:
    spec = AgentSpec(
        id="interview-daily",
        title="Interview",
        category=AgentCategory.ASSISTANT,
        tools=ToolConfig(allowed_tools=["Read", "Bash", "mcp__notion__API-post-page"]),
    )

    assert extract_required_mcp_servers(spec) == {"notion"}


def test_extract_required_mcp_servers_returns_empty_without_mcp_tools() -> None:
    spec = AgentSpec(
        id="daily-ai-news",
        title="Daily News",
        category=AgentCategory.AGGREGATION,
        tools=ToolConfig(allowed_tools=["Read", "Bash", "x_search", "youtube_search"]),
    )

    assert extract_required_mcp_servers(spec) == set()


def test_extract_required_mcp_servers_prefers_explicit_servers() -> None:
    spec = AgentSpec(
        id="explicit-mcp",
        title="Explicit MCP",
        category=AgentCategory.ASSISTANT,
        tools=ToolConfig(
            mcp_servers=["notion", "github"],
            allowed_tools=["mcp__notion__API-post-page"],
        ),
    )

    assert extract_required_mcp_servers(spec) == {"notion", "github"}


@pytest.mark.asyncio
async def test_create_loop_from_id_raises_for_missing_spec(runtime: AgentRuntime) -> None:
    with pytest.raises(AgentError, match="SKILL_SPEC_NOT_FOUND"):
        await runtime.create_loop_from_id("missing")


@pytest.mark.asyncio
async def test_create_loop_inline_returns_whitelisted_tools(runtime: AgentRuntime) -> None:
    loop = await runtime.create_loop_inline(
        role="测试",
        system_prompt="你是测试 agent",
        tools=["Read"],
    )

    assert sorted(tool.name for tool in loop._executor.list_definitions()) == ["Read"]  # noqa: SLF001


@pytest.mark.asyncio
async def test_max_depth_zero_removes_recursive_tools(runtime: AgentRuntime) -> None:
    spec = AgentSpec(
        id="code-reviewer",
        title="代码审查",
        category=AgentCategory.CODING,
        system_prompt="review",
        tools=ToolConfig(),
    )
    spec.sub_agents.max_depth = 0

    loop = await runtime.create_loop(spec, workspace="workspace")
    tool_names = [tool.name for tool in loop._executor.list_definitions()]  # noqa: SLF001

    assert "dispatch_agent" not in tool_names
    assert "orchestrate_agents" not in tool_names
    assert "spawn_agent" not in tool_names


@pytest.mark.asyncio
async def test_sub_agent_loop_excludes_query_specs_and_recursive_tools(
    runtime: AgentRuntime,
) -> None:
    spec = AgentSpec(
        id="researcher",
        title="Research",
        category=AgentCategory.RESEARCH,
        system_prompt="research",
        tools=ToolConfig(),
    )
    runtime._deps.spec_registry.register(spec)  # noqa: SLF001

    loop = await runtime.create_loop_from_id("researcher", is_sub_agent=True)
    tool_names = [tool.name for tool in loop._executor.list_definitions()]  # noqa: SLF001

    assert "query_specs" not in tool_names
    assert "dispatch_agent" not in tool_names
    assert "orchestrate_agents" not in tool_names
    assert "spawn_agent" not in tool_names
