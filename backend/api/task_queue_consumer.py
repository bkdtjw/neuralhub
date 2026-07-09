from __future__ import annotations

# 兼容壳：真实现全部在 backend.core（生产 sub_worker 走 core）。此处仅 re-export，供历史/测试导入路径使用。
# D2（知识心跳保活）/C5（父取消联动）现已并入 core.task_queue_consumer / core.task_queue_agent_runner。
from backend.core.task_queue_agent_runner import _build_sub_agent_loop
from backend.core.task_queue_consumer import (
    SubAgentConsumerContext,
    TaskHandler,
    consume_next_sub_agent_task,
    default_task_handlers,
    execute_sub_agent_task,
)

__all__ = [
    "SubAgentConsumerContext",
    "TaskHandler",
    "_build_sub_agent_loop",
    "consume_next_sub_agent_task",
    "default_task_handlers",
    "execute_sub_agent_task",
]
