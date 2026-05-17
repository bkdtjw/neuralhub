from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class CardHandlerDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feishu_client: Any = None
    chat_id: str = ""
    session_factory: Any = None
    config_dir: Path = Path("config/sites")


class ActionRoute(BaseModel):
    action_type: str = ""
    prefix: str = ""
    target: str = ""
    user_id: str = "default"
    chat_id: str = ""
    selector: str = ""


def parse_action_route(payload: dict[str, Any]) -> ActionRoute:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action = event.get("action", {}) if isinstance(event, dict) else {}
    value = action.get("value", {}) if isinstance(action, dict) else {}
    if isinstance(value, str):
        action_type = value
        value_dict: dict[str, Any] = {}
    else:
        value_dict = value if isinstance(value, dict) else {}
        action_type = str(value_dict.get("action_type") or value_dict.get("action") or "")
    prefix, _, target = action_type.partition(":")
    return ActionRoute(
        action_type=action_type,
        prefix=prefix,
        target=target,
        user_id=_operator_id(event),
        chat_id=_chat_id(event),
        selector=str(value_dict.get("selector", "")),
    )


def _operator_id(event: Any) -> str:
    if not isinstance(event, dict):
        return "default"
    operator = event.get("operator", {})
    if not isinstance(operator, dict):
        return "default"
    nested = operator.get("operator_id", {})
    if isinstance(nested, dict):
        return str(nested.get("open_id") or nested.get("user_id") or "default")
    return str(operator.get("open_id") or operator.get("user_id") or "default")


def _chat_id(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    context = event.get("context", {})
    if isinstance(context, dict):
        return str(context.get("open_chat_id") or "")
    return ""


__all__ = ["ActionRoute", "CardHandlerDeps", "parse_action_route"]
