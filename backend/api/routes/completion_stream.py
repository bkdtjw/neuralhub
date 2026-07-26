from __future__ import annotations

import asyncio, json
from collections.abc import AsyncIterator
from time import time
from typing import Any

from backend.common.types import Message, ToolCall, ToolResult

_POLL_INTERVAL_SECONDS = 0.1


def _chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": int(time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _tool_call_delta(call: ToolCall) -> dict[str, Any]:
    return {
        "tool_calls": [
            {
                "index": 0,
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
        ]
    }


async def event_stream(loop: Any, model: str, user_message: str) -> AsyncIterator[str]:
    """把 AgentLoop 事件转成 OpenAI 兼容 SSE；断连时取消 run，避免子进程 provider 空跑烧额度。"""
    queue: asyncio.Queue[str] = asyncio.Queue()

    def on_event(event: Any) -> None:
        if event.type == "message" and isinstance(event.data, Message) and event.data.content:
            queue.put_nowait(_chunk(model, {"content": event.data.content}))
        if event.type == "tool_call" and isinstance(event.data, ToolCall):
            queue.put_nowait(_chunk(model, _tool_call_delta(event.data)))
        if event.type == "tool_result" and isinstance(event.data, ToolResult):
            queue.put_nowait(_chunk(model, {"content": event.data.output}))

    loop.on(on_event)
    task = asyncio.create_task(loop.run(user_message))
    try:
        while True:
            if task.done() and queue.empty():
                break
            try:
                yield await asyncio.wait_for(queue.get(), timeout=_POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue
        await task
        yield "data: [DONE]\n\n"
    except Exception as exc:  # noqa: BLE001
        yield f"data: {json.dumps({'error': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        # 客户端断连走 GeneratorExit（BaseException，上面 except 接不住）：
        # 不取消的话这轮会一直跑完，对 claude_code 这类子进程 provider 等于白烧额度
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


__all__ = ["event_stream"]
