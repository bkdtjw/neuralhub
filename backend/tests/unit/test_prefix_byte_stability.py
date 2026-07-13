from __future__ import annotations

import json
from typing import Any

from backend.adapters.anthropic_support import build_payload
from backend.adapters.logging_support import log_prefix_fingerprint
from backend.common.types import AgentConfig, Message, ToolDefinition, ToolParameterSchema
from backend.core.s01_agent_loop.agent_loop_support import build_cache_prefix_hash, build_llm_request
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools


def _config(workspace: str) -> AgentConfig:
    return AgentConfig(
        model="model",
        provider="provider",
        system_prompt="stable system",
        workspace=workspace,
        max_tokens=64,
    )


def _payload_text(workspace: str, tools: list[ToolDefinition]) -> str:
    request = build_llm_request(
        _config(workspace),
        [Message(role="user", kind="user_request", content="hi")],
        tools,
    )
    return json.dumps(build_payload(request, "model", stream=False), ensure_ascii=False)


def test_same_input_builds_byte_identical_payload() -> None:
    tools = [
        ToolDefinition(
            name="file_read",
            description="Read files",
            category="file-ops",
            parameters=ToolParameterSchema(properties={"path": {"type": "string"}}),
        )
    ]
    assert _payload_text("/ws", tools) == _payload_text("/ws", tools)


def test_registry_rebuild_produces_byte_identical_payload(tmp_path) -> None:
    texts = []
    for _ in range(2):
        registry = ToolRegistry()
        register_builtin_tools(registry, str(tmp_path), mode="auto")
        texts.append(_payload_text(str(tmp_path), registry.list_definitions()))
    assert texts[0] == texts[1]


def test_cache_prefix_hash_sensitive_to_property_order() -> None:
    ab = ToolDefinition(
        name="t",
        description="d",
        category="shell",
        parameters=ToolParameterSchema(properties={"a": {"type": "string"}, "b": {"type": "string"}}),
    )
    ba = ToolDefinition(
        name="t",
        description="d",
        category="shell",
        parameters=ToolParameterSchema(properties={"b": {"type": "string"}, "a": {"type": "string"}}),
    )
    assert build_cache_prefix_hash("s", [ab]) != build_cache_prefix_hash("s", [ba])


class _CaptureLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.records.append({"event": event, **fields})


def test_prefix_fingerprint_logs_tool_names() -> None:
    tools = [
        ToolDefinition(
            name="file_read",
            description="Read files",
            category="file-ops",
            parameters=ToolParameterSchema(properties={"path": {"type": "string"}}),
        )
    ]
    request = build_llm_request(
        _config("/ws"),
        [Message(role="user", kind="user_request", content="hi")],
        tools,
    )
    payload = build_payload(request, "model", stream=False)
    logger = _CaptureLogger()

    log_prefix_fingerprint(logger, request, payload)

    assert logger.records and logger.records[0]["event"] == "llm_prefix_fingerprint"
    record = logger.records[0]
    assert record["tools_names"] == "file_read"
    assert record["tools_count"] == "1"
    assert len(record["payload_prefix_sha"]) == 16
    assert record["cache_prefix_hash"] == request.cache_prefix_hash[:16]
