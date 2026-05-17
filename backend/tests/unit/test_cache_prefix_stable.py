from __future__ import annotations

from backend.common.types import AgentConfig, Message, ToolDefinition, ToolParameterSchema
from backend.core.s01_agent_loop.agent_loop_support import build_llm_request


def _tool(name: str = "file_read") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Read files",
        category="file-ops",
        parameters=ToolParameterSchema(properties={"path": {"type": "string"}}),
    )


def test_cache_prefix_hash_is_stable_across_recent_messages() -> None:
    config = AgentConfig(model="model", provider="provider", system_prompt="stable")
    history_a = [
        Message(role="system", content="stable"),
        Message(role="user", content="[对话历史摘要]\nkeep this"),
        Message(role="user", content="first turn"),
    ]
    history_b = [
        Message(role="system", content="stable"),
        Message(role="user", content="[对话历史摘要]\nkeep this"),
        Message(role="user", content="second turn"),
    ]

    first = build_llm_request(config, history_a, [_tool()])
    second = build_llm_request(config, history_b, [_tool()])

    assert first.cache_prefix_hash == second.cache_prefix_hash
    assert first.system_prompt == "stable"
    assert first.summary_message is not None
    assert [message.role for message in first.recent_messages] == ["user"]
    assert [message.role for message in first.messages] == ["system", "user", "user"]


def test_cache_prefix_hash_changes_when_tools_change() -> None:
    config = AgentConfig(model="model", provider="provider", system_prompt="stable")
    history = [Message(role="system", content="stable"), Message(role="user", content="hi")]

    first = build_llm_request(config, history, [_tool("file_read")])
    second = build_llm_request(config, history, [_tool("file_write")])

    assert first.cache_prefix_hash != second.cache_prefix_hash
