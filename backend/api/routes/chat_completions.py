from __future__ import annotations

import asyncio, json
from collections.abc import AsyncIterator
from time import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.routes.mcp import mcp_server_manager
from backend.api.routes.providers import provider_manager
from backend.common import AgentError, LLMError
from backend.common.types import AgentConfig, Message, ToolCall, ToolResult
from backend.config.settings import settings as app_settings
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.mcp import MCPToolBridge
from backend.schemas.completion import ChatCompletionChoice, ChatCompletionRequest, ChatCompletionResponse, ChatCompletionUsage

router = APIRouter(tags=["completions"])

def _to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return "" if content is None else str(content)

def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {}

def _openai_messages_to_internal(messages: list[dict]) -> list[Message]:
    out: list[Message] = []
    for item in messages:
        role = item.get("role", "user")
        if role == "assistant":
            calls = [ToolCall(id=tc.get("id", ""), name=tc.get("function", {}).get("name", ""), arguments=_parse_args(tc.get("function", {}).get("arguments", ""))) for tc in item.get("tool_calls", []) or []]
            provider_metadata: dict[str, Any] = {}
            reasoning = item.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                provider_metadata["reasoning_content"] = reasoning
            out.append(
                Message(
                    role="assistant",
                    content=_to_text(item.get("content")),
                    tool_calls=calls or None,
                    provider_metadata=provider_metadata,
                )
            )
        elif role == "tool":
            res = ToolResult(tool_call_id=item.get("tool_call_id", ""), output=_to_text(item.get("content")))
            out.append(Message(role="tool", content="", tool_results=[res]))
        else:
            out.append(Message(role=role if role in {"user", "system"} else "user", content=_to_text(item.get("content"))))
    return out

def _internal_message_to_openai(message: Message, model: str) -> ChatCompletionResponse:
    choice: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        choice["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}} for c in message.tool_calls]
    return ChatCompletionResponse(id=message.id, created=int(message.timestamp.timestamp()), model=model, choices=[ChatCompletionChoice(message=choice, finish_reason="tool_calls" if message.tool_calls else "stop")], usage=ChatCompletionUsage())


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: ChatCompletionRequest, raw_request: Request) -> Any:
    try:
        internal = _openai_messages_to_internal(request.messages)
        user_idx = max((i for i, msg in enumerate(internal) if msg.role == "user"), default=-1)
        if user_idx < 0:
            raise HTTPException(status_code=400, detail={"code": "INVALID_MESSAGES", "message": "No user message found"})
        adapter = await provider_manager.get_adapter(request.provider_id)
        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            request.workspace,
            mode=request.permission_mode,
            adapter=adapter,
            default_model=request.model,
            feishu_webhook_url=app_settings.feishu_webhook_url or None,
            feishu_secret=app_settings.feishu_webhook_secret or None,
            youtube_api_key=app_settings.youtube_api_key or None,
            youtube_proxy_url=app_settings.youtube_proxy_url or None,
            twitter_username=app_settings.twitter_username or None,
            twitter_email=app_settings.twitter_email or None,
            twitter_password=app_settings.twitter_password or None,
            twitter_proxy_url=app_settings.twitter_proxy_url or None,
            twitter_cookies_file=app_settings.twitter_cookies_file or None,
            agent_runtime=getattr(raw_request.app.state, "agent_runtime", None),
            spec_registry=getattr(raw_request.app.state, "spec_registry", None),
            task_queue=getattr(raw_request.app.state, "task_queue", None),
        )
        await MCPToolBridge(mcp_server_manager, registry).sync_all()
        loop = AgentLoop(config=AgentConfig(model=request.model, system_prompt=""), adapter=adapter, tool_registry=registry)
        loop.message_history.restore(internal[:user_idx])
        user_message = internal[user_idx].content
        if not request.stream:
            return _internal_message_to_openai(await loop.run(user_message), request.model)

        async def event_generator() -> AsyncIterator[str]:
            queue: asyncio.Queue[str] = asyncio.Queue()

            def emit(delta: dict[str, Any], finish_reason: str | None = None) -> None:
                payload = {"id": "chatcmpl-stream", "object": "chat.completion.chunk", "created": int(time()), "model": request.model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
                queue.put_nowait(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

            def on_event(event: Any) -> None:
                if event.type == "message" and isinstance(event.data, Message) and event.data.content:
                    emit({"content": event.data.content})
                if event.type == "tool_call" and isinstance(event.data, ToolCall):
                    emit({"tool_calls": [{"index": 0, "id": event.data.id, "type": "function", "function": {"name": event.data.name, "arguments": json.dumps(event.data.arguments, ensure_ascii=False)}}]})
                if event.type == "tool_result" and isinstance(event.data, ToolResult):
                    emit({"content": event.data.output})

            loop.on(on_event)
            task = asyncio.create_task(loop.run(user_message))
            try:
                while True:
                    if task.done() and queue.empty():
                        break
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                await task
                yield "data: [DONE]\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"data: {json.dumps({'error': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except HTTPException:
        raise
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code or 400, detail={"code": exc.code, "message": exc.message}) from exc
    except AgentError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(exc)}) from exc


__all__ = ["router", "provider_manager"]
