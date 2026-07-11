from __future__ import annotations

from typing import Any

from backend.core.s13_knowledge import KnowledgeBase


def build_kb_switch_card(
    kbs: list[KnowledgeBase],
    current_kb_id: str,
) -> dict[str, Any]:
    current = next((item for item in kbs if item.id == current_kb_id), None)
    current_name = current.name if current is not None else "默认库"
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"当前知识库：**{current_name}**\n"
                    "之后发送的问题会优先检索该知识库，上传的文件也会进入该知识库。"
                ),
            },
        },
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "plain_text", "content": "选择要使用的知识库"}},
    ]
    for kb in kbs:
        selected = kb.id == current_kb_id
        label = f"{'✓ ' if selected else ''}{kb.name}"
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": "primary" if selected else "default",
                        "value": {"action_type": "kb_select", "kb_id": kb.id},
                    }
                ],
            }
        )
    elements.append(
        {
            "tag": "hr",
        }
    )
    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"已选中：**{current_name}**",
            },
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "NeuralHub 知识库"},
        },
        "elements": elements,
    }


__all__ = ["build_kb_switch_card"]
