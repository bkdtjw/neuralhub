from __future__ import annotations

# 兼容壳：真实现全部在 backend.core.task_queue_consumer_helpers（生产走 core）。此处仅 re-export。
from backend.core.task_queue_consumer_helpers import (
    HEARTBEAT_INTERVAL_SECONDS,
    LEASE_EXTENSION_SECONDS,
    _heartbeat_loop,
    _loop_config_value,
    _payload_log_context,
    _record_task_failure,
    _restored_messages,
    _run_with_heartbeat,
    _safe_fail,
    _timeout_seconds,
    _tool_call_count,
)

__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "LEASE_EXTENSION_SECONDS",
    "_heartbeat_loop",
    "_loop_config_value",
    "_payload_log_context",
    "_record_task_failure",
    "_restored_messages",
    "_run_with_heartbeat",
    "_safe_fail",
    "_timeout_seconds",
    "_tool_call_count",
]
