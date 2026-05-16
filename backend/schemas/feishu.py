"""Pydantic models for Feishu card system (CardKit template + callback)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Card registry config models (maps to feishu_cards.json) ---


class FeishuCardVariableConfig(BaseModel):
    """A single variable in a card template."""

    type: str = "string"
    required: bool = True
    description: str = ""


class FeishuCardConfig(BaseModel):
    """A single card scenario entry from feishu_cards.json."""

    template_id: str
    template_version: str = "1.0.0"
    description: str = ""
    trigger_tools: list[str] = Field(default_factory=list)
    variables: dict[str, FeishuCardVariableConfig] = Field(default_factory=dict)


class FeishuCardRegistryPayload(BaseModel):
    """Root structure of feishu_cards.json."""

    cards: dict[str, FeishuCardConfig] = Field(default_factory=dict)


# --- Card action callback models ---


class FeishuCardActionValue(BaseModel):
    """The value payload inside action (action_type + arbitrary data)."""

    action_type: str = ""
    model_config = {"extra": "allow"}


class FeishuCardAction(BaseModel):
    """A single action (button click) from card callback."""

    value: FeishuCardActionValue = Field(default_factory=FeishuCardActionValue)
    tag: str = "button"


class FeishuCardActionPayload(BaseModel):
    """Full payload received from Feishu card action callback."""

    open_id: str = ""
    open_message_id: str = ""
    token: str = ""
    action: FeishuCardAction = Field(default_factory=FeishuCardAction)
    model_config = {"extra": "allow"}


class FeishuCardActionResponse(BaseModel):
    """Response for card action callback (toast or card update)."""

    toast: dict[str, str] | None = None
    card: dict[str, Any] | None = None


__all__ = [
    "FeishuCardVariableConfig",
    "FeishuCardConfig",
    "FeishuCardRegistryPayload",
    "FeishuCardActionValue",
    "FeishuCardAction",
    "FeishuCardActionPayload",
    "FeishuCardActionResponse",
]
