from __future__ import annotations

from pydantic import BaseModel, Field


class LoginCardInput(BaseModel):
    action_type: str
    values: dict[str, str] = Field(default_factory=dict)


class LoginAssistResult(BaseModel):
    status: str
    detail: str = ""


__all__ = ["LoginAssistResult", "LoginCardInput"]
