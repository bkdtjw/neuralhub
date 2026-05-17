from __future__ import annotations

from pydantic import BaseModel, Field


class CardAction(BaseModel):
    action_type: str
    payload: dict[str, str] = Field(default_factory=dict)

    def to_value(self) -> dict[str, str]:
        return {"action_type": self.action_type, "action": self.action_type, **self.payload}


class ButtonSpec(BaseModel):
    text: str
    action: CardAction
    button_type: str = "default"


def button(spec: ButtonSpec) -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": spec.text},
        "type": spec.button_type,
        "value": spec.action.to_value(),
    }


def card(title: str, elements: list[dict], template: str = "blue") -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


__all__ = ["ButtonSpec", "CardAction", "button", "card"]
