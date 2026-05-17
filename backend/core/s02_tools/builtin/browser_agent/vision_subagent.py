from __future__ import annotations

import base64
import json

from pydantic import BaseModel

from backend.adapters.role_router import RoleRouter
from backend.common.types import LLMRequest, Message, ToolDefinition, ToolParameterSchema

from .models import VisionObservation

SYSTEM_PROMPT_VISION = """你是浏览器视觉感知 subagent。你只看一张截图，回答关于这一帧的问题。
你不持有任务历史，不要假设上下文。每次回答都基于当前看到的截图。
返回必须调用 report_observation 工具，包含：
  - page_summary: 一句话描述当前页是什么
  - visible_elements: 屏幕上的关键可交互元素（按钮、输入框、链接），
    每个含 description + selector_hint + bbox
  - target_element: 与提问最相关的元素（若问题涉及）
  - suggested_next_action: 自然语言建议（仅作主 agent 参考）
  - screenshot_importance: 0.0 - 1.0，当前截图是否值得作为证据保留/发送
  - task_relevance: 0.0 - 1.0，当前截图与用户目标的直接相关度
  - screenshot_reason: 若重要，说明原因；登录、验证码、阻塞页即使相关度低也可能重要
  - confidence: 0.0 - 1.0
  - need_human: 看不懂或风险高 → true

bbox 坐标系：左上原点，单位 px，对应 viewport={viewport_w}x{viewport_h}
（device_scale_factor=1，截图坐标 = 点击坐标）。
"""


class VisionRequest(BaseModel):
    screenshot: bytes
    url: str
    title: str = ""
    viewport: tuple[int, int] = (1280, 720)
    task_hint: str = ""
    last_action_kind: str = ""


async def observe(
    request: VisionRequest,
    role_router: RoleRouter,
    provider_id: str = "",
) -> VisionObservation:
    provider = await role_router.resolve_provider("vision", provider_id)
    adapter = await role_router.get_adapter(provider.id)
    response = await adapter.complete(  # type: ignore[attr-defined]
        LLMRequest(
            model=provider.default_model,
            messages=_build_messages(request),
            tools=[_report_observation_tool()],
            tool_choice={"type": "function", "function": {"name": "report_observation"}},
            temperature=0.0,
            max_tokens=4096,
        )
    )
    return _parse_observation(response.content, response.tool_calls)


def _build_messages(request: VisionRequest) -> list[Message]:
    width, height = request.viewport
    prompt = SYSTEM_PROMPT_VISION.format(viewport_w=width, viewport_h=height)
    image_url = f"data:image/png;base64,{base64.b64encode(request.screenshot).decode('ascii')}"
    content = [
        {"type": "image_url", "image_url": {"url": image_url}},
        {"type": "text", "text": _format_question(request)},
    ]
    return [
        Message(role="system", content=prompt),
        Message.model_construct(role="user", content=content),
    ]


def _format_question(request: VisionRequest) -> str:
    return "\n".join(
        [
            f"当前 URL: {request.url}",
            f"当前标题: {request.title}",
            f"viewport: {request.viewport[0]}x{request.viewport[1]}",
            f"局部问题: {request.task_hint or '描述当前页面并找出可操作元素'}",
            f"上一步动作: {request.last_action_kind or 'none'}",
        ]
    )


def _report_observation_tool() -> ToolDefinition:
    element_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "selector_hint": {"type": "string"},
            "bbox": {
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
            },
            "confidence": {"type": "number"},
        },
        "required": ["description"],
    }
    return ToolDefinition(
        name="report_observation",
        description="Report visible browser page elements from the current screenshot.",
        category="browser",
        parameters=ToolParameterSchema(
            properties={
                "page_summary": {"type": "string"},
                "visible_elements": {"type": "array", "items": element_schema},
                "target_element": {"anyOf": [element_schema, {"type": "null"}]},
                "suggested_next_action": {"type": "string"},
                "screenshot_importance": {"type": "number"},
                "task_relevance": {"type": "number"},
                "screenshot_reason": {"type": "string"},
                "confidence": {"type": "number"},
                "need_human": {"type": "boolean"},
            },
            required=["page_summary"],
        ),
    )


def _parse_observation(raw_text: str, tool_calls: object) -> VisionObservation:
    try:
        calls = tool_calls if isinstance(tool_calls, list) else []
        if not calls:
            return _parse_failed(raw_text)
        arguments = getattr(calls[0], "arguments", {})
        if not isinstance(arguments, dict):
            return _parse_failed(raw_text)
        normalized = _normalize_observation_arguments(arguments)
        observation = VisionObservation.model_validate(normalized)
        return observation.model_copy(update={"raw_text": raw_text})
    except Exception as exc:  # noqa: BLE001
        detail = raw_text or json.dumps({"error": str(exc)}, ensure_ascii=False)
        return _parse_failed(detail)


def _normalize_observation_arguments(arguments: dict[str, object]) -> dict[str, object]:
    normalized = dict(arguments)
    target = normalized.get("target_element")
    if isinstance(target, str):
        normalized["target_element"] = _json_object_or_none(target)
    elements = normalized.get("visible_elements")
    if isinstance(elements, str):
        parsed = _json_list_or_none(elements)
        if parsed is not None:
            normalized["visible_elements"] = parsed
    return normalized


def _json_object_or_none(raw: str) -> dict[str, object] | None:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_list_or_none(raw: str) -> list[object] | None:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _parse_failed(raw_text: str) -> VisionObservation:
    return VisionObservation(raw_text=raw_text, need_human=True, confidence=0.0)


__all__ = ["SYSTEM_PROMPT_VISION", "VisionRequest", "observe"]
