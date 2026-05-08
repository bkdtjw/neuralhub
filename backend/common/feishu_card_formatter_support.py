"""Support helpers for LLM-based Feishu card formatting."""

from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from backend.common.feishu_card import FeishuCardError

_MAX_PREVIEW_CHARS = 500
_MAX_ITEM_CHARS = 90


def clean_llm_json(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise FeishuCardError("CARD_FORMAT_JSON_ERROR", "LLM returned empty response")
    return _extract_json_object(_strip_markdown_fence(text))


def parse_variables(raw: str) -> dict[str, str]:
    payload = json.loads(clean_llm_json(raw))
    if not isinstance(payload, dict):
        raise FeishuCardError(
            "CARD_FORMAT_TYPE_ERROR",
            f"LLM returned non-object JSON: {type(payload).__name__}",
        )
    return {str(key): _stringify(value) for key, value in payload.items()}


def build_retry_prompt(prompt: str, raw: str, error: str) -> str:
    preview = compact_preview(raw)
    return (
        "上一次输出不是合法 JSON，不能被系统解析。\n"
        f"解析错误：{error}\n"
        f"上一次输出预览：{preview}\n\n"
        "请重新完成同一个任务。只输出一个 JSON 对象，不要解释，不要 markdown 代码块，"
        "不要在 JSON 前后添加任何文字。\n\n"
        f"{prompt}"
    )


def compact_preview(value: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    text = " ".join((value or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def build_fallback_variables(
    missing_vars: dict[str, Any],
    agent_reply: str,
) -> dict[str, str]:
    title = _first_heading(agent_reply) or "任务执行完成"
    items = _extract_key_items(agent_reply)
    summary = _build_summary(title, items, agent_reply)
    result_summary = _build_result_summary(items, agent_reply)

    fallback: dict[str, str] = {}
    for key in missing_vars:
        lowered = key.lower()
        if key == "result_summary":
            fallback[key] = result_summary
        elif "summary" in lowered:
            fallback[key] = summary
        else:
            fallback[key] = ""
    return fallback


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return ""
    body = text[first_newline + 1 :]
    if "```" in body:
        body = body.rsplit("```", 1)[0]
    return body.strip()


def _extract_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, end = decoder.raw_decode(text[index:])
        except JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return text[index : index + end]
    raise FeishuCardError("CARD_FORMAT_JSON_ERROR", "LLM response has no JSON object")


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _extract_key_items(text: str, limit: int = 3) -> list[str]:
    section = _preferred_section(text)
    candidates = _table_items(section) + _bullet_items(section) + _heading_items(text)
    items: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        item = _clean_item(candidate)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= limit:
            return items
    return items


def _preferred_section(text: str) -> str:
    markers = ("今日必看", "关键发现", "热点头条", "项目拷打", "专题八股")
    lines = text.splitlines()
    start = next(
        (idx for idx, line in enumerate(lines) if any(marker in line for marker in markers)),
        None,
    )
    if start is None:
        return text
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("## ") and idx > start:
            end = idx
            break
    return "\n".join(lines[start:end])


def _table_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 2 and re.search(r"\d", cells[0]):
            items.append(cells[1])
    return items


def _bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:])
        elif re.match(r"^\d+\.\s+", stripped):
            items.append(re.sub(r"^\d+\.\s+", "", stripped))
    return items


def _heading_items(text: str) -> list[str]:
    return [line.lstrip("#").strip() for line in text.splitlines() if line.startswith("### ")]


def _clean_item(value: str) -> str:
    text = re.sub(r"[*_`>#]", "", value).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:_MAX_ITEM_CHARS] + ("..." if len(text) > _MAX_ITEM_CHARS else "")


def _build_summary(title: str, items: list[str], text: str) -> str:
    if items:
        return f"✅ {title}\n" + "\n".join(f"• {item}" for item in items[:2])
    preview = compact_preview(text, 120) or "任务已完成，但未提取到可展示摘要。"
    return f"✅ {title}\n{preview}"


def _build_result_summary(items: list[str], text: str) -> str:
    if items:
        return "关键发现包括：\n" + "\n".join(f"- {item}" for item in items)
    return f"关键发现包括：\n- {compact_preview(text, 120) or '暂无可提取内容'}"


__all__ = [
    "build_fallback_variables",
    "build_retry_prompt",
    "clean_llm_json",
    "compact_preview",
    "parse_variables",
]
