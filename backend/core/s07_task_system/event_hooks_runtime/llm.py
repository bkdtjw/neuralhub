from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from backend.common.types import LLMRequest, Message
from backend.core.s07_task_system.event_hooks import (
    AssessFn,
    AssessRequest,
    Assessment,
    Development,
    HookSignal,
)
from backend.core.s07_task_system.event_hooks_runtime import HookRuntimeError

if TYPE_CHECKING:
    from backend.adapters.base import LLMAdapter

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_PARSE_FALLBACK = Assessment(materiality=0, summary="（LLM 解析失败）", developments=[])


def make_assess_fn(adapter: LLMAdapter, model: str) -> AssessFn:
    async def assess(request: AssessRequest) -> Assessment:
        try:
            llm_request = LLMRequest(
                model=model,
                messages=[Message(role="user", content=_build_prompt(request))],
                temperature=0.2,
                max_tokens=600,
            )
            response = await adapter.complete(llm_request)
            return _parse_assessment(response.content)
        except HookRuntimeError:
            raise
        except Exception as exc:
            raise HookRuntimeError(f"HOOK_RUNTIME_ASSESS_ERROR: {exc}") from exc

    return assess


def _build_prompt(request: AssessRequest) -> str:
    signal_lines = "\n".join(_signal_line(signal) for signal in request.signals[:20])
    if not signal_lines:
        signal_lines = "（本轮没有新信号）"
    prev_summary = request.prev_summary or "（无）"
    recent_lines = "\n".join(f"- {text.replace(chr(10), ' ')[:220]}" for text in request.recent_developments[:20])
    if not recent_lines:
        recent_lines = "（无）"
    keywords = "、".join(request.hook.twitter.keywords) or request.hook.name
    return (
        "你是事件进展研判助手。请判断本轮信号相对旧局势是否重大、可信、值得推送。\n\n"
        f"Hook 名称：{request.hook.name}\n"
        f"追踪主题（只关心与这些直接相关的实质进展）：{keywords}\n"
        f"旧局势摘要：{prev_summary}\n\n"
        f"本轮信号（最多 20 条）：\n{signal_lines}\n\n"
        "已报告过的进展（这些是过去已记录的，绝不要重复，只输出相对它们真正新的）：\n"
        f"{recent_lines}\n\n"
        "===== 相关性与去噪规则（最重要，先过这一关再谈重大）=====\n"
        "只有「直接讲述追踪主题本身的实质新进展」才算 development，例如：正式发布/上线/开放、官方公告、"
        "新增能力或参数、价格与可用性、确切时间表、权威信源确认的事实。\n"
        "下列一律视为噪声：materiality 给 ≤15，且绝不放进 developments：\n"
        "1) 只是顺带提到关键词、真正主题却是别的——如出口管制/监管/政策/地缘、把它当类比或调侃、"
        "「X 就像<主题>」之类。关键词命中 ≠ 相关。\n"
        "2) 重复旧状态、没有变化的陈述（含「仍」「依旧」「还是」「一如既往」等）。\n"
        "3) 传言、猜测、预测、个人观点、营销吹捧、情绪宣泄，且无权威/官方信源支撑。\n"
        "4) 与「旧局势摘要」或「已报告过的进展」实质重复的内容。\n"
        "判断口径：先问『这条到底在讲什么』，主题不是追踪对象本身的实质进展就剔除；宁可漏报，不要骚扰用户。\n\n"
        "请只输出 JSON，不要 markdown、不要解释。格式必须是：\n"
        '{"materiality": <0-100 整数，这条进展有多重大/可信>, '
        '"summary": "<一句中文当前局势>", '
        '"developments": [{"text": "<一句中文进展，简洁、别照抄原文>", '
        '"ts": "<必须 ISO8601（如 2026-06-27T15:00:00Z），取该进展来源时间>", "source": "twitter|exa"}], '
        '"resolved": <bool，事件是否已收尾>}\n'
        "developments 必须是相比「旧局势摘要」和「已报告过的进展」的新增重大进展；每条一句话、提炼非照搬，"
        "按时间从新到旧排列（最新在前）。\n"
        "若相比旧摘要没有实质新进展，或全部命中上面四类噪声，developments 必须返回空数组 []；"
        "没新东西就空，不要硬凑旧闻或噪声，这决定是否打扰用户。\n"
        "首次（旧摘要为空或无）时，把当前最重要的几条「真正相关」的现状作为 developments 列出，同样剔除噪声。\n"
        "拿不准、像噪声、旧闻或重复内容时，materiality 给低分。"
    )


def _signal_line(signal: HookSignal) -> str:
    author = signal.author or "unknown"
    text = signal.text.replace("\n", " ")[:200]
    return (
        f"[{signal.source}/{signal.lane}] {signal.ts or 'unknown_time'} @{author} "
        f"({signal.engagement})：{text}"
    )


def _parse_assessment(raw: str) -> Assessment:
    try:
        data = json.loads(_strip_json_fence(raw))
        if not isinstance(data, dict):
            return _PARSE_FALLBACK
        materiality = _clamp_materiality(data.get("materiality", 0))
        status_hint = "resolved" if data.get("resolved") is True else None
        return Assessment(
            materiality=materiality,
            summary=str(data.get("summary", "")),
            status_hint=status_hint,
            developments=_parse_developments(data.get("developments")),
        )
    except Exception:
        return _PARSE_FALLBACK


def _parse_developments(value: Any) -> list[Development]:
    if not isinstance(value, list):
        return []
    developments: list[Development] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if text is None or not str(text).strip():
            continue
        developments.append(
            Development(
                text=str(text).strip(),
                ts=str(item.get("ts", "")),
                source=str(item.get("source", "")),
            )
        )
        if len(developments) >= 8:
            break
    return developments


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    match = _JSON_FENCE.match(text)
    return match.group(1).strip() if match else text


def _clamp_materiality(value: Any) -> int:
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(100, numeric))


__all__ = ["make_assess_fn"]
