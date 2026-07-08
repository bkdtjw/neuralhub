from __future__ import annotations

import json

from backend.common.types import Message, ToolDefinition


def _is_cjk(char: str) -> bool:
    """判断字符是否为 CJK 表意文字/假名/谚文/全角等，按 1 token/字计。"""
    code = ord(char)
    return (
        0x3400 <= code <= 0x9FFF  # CJK 基本区 + 扩展 A
        or 0xF900 <= code <= 0xFAFF  # CJK 兼容表意文字
        or 0x3040 <= code <= 0x30FF  # 平假名 + 片假名
        or 0xAC00 <= code <= 0xD7AF  # 谚文音节
        or 0xFF00 <= code <= 0xFFEF  # 全角/半角形式
    )


def estimate_tokens(text: str) -> int:
    """按字符类别加权估算 token：CJK 类每字 1 token，其余字符累计后 //4。"""
    cjk = 0
    other = 0
    for char in text:
        if _is_cjk(char):
            cjk += 1
        else:
            other += 1
    return cjk + other // 4


class TokenCounter:
    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        return estimate_tokens(text)

    def estimate_messages_tokens(self, messages: list[Message]) -> int:
        total = 0
        for message in messages:
            total += self._estimate_text_tokens(message.content)
            for tool_call in message.tool_calls or []:
                arguments = json.dumps(
                    tool_call.arguments,
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                total += self._estimate_text_tokens(arguments)
            for tool_result in message.tool_results or []:
                total += self._estimate_text_tokens(tool_result.output)
        return total

    def estimate_tools_tokens(self, definitions: list[ToolDefinition]) -> int:
        total = 0
        for definition in definitions:
            tool_text = json.dumps(
                definition.model_dump(),
                default=str,
                ensure_ascii=False,
                sort_keys=True,
            )
            total += self._estimate_text_tokens(tool_text)
        return total


__all__ = ["TokenCounter", "estimate_tokens"]
