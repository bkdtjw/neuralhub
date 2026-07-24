from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


class AddProviderRequest(BaseModel):
    name: str
    provider_type: str
    base_url: str
    api_key: str = ""
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    enable_prompt_cache: bool = False
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    roles: str = ""


class ProviderResponse(BaseModel):
    """Provider response with masked api key preview."""

    id: str
    name: str
    provider_type: str
    base_url: str
    api_key_preview: str = Field(validation_alias=AliasChoices("api_key_preview", "api_key"))
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    enable_prompt_cache: bool = False
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True
    roles: str = ""


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int


class DetectModelsRequest(BaseModel):
    provider_type: str
    base_url: str = ""
    api_key: str = ""
    provider_id: str | None = None


class DetectModelsResponse(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list)
    message: str = ""


class ProviderCreateRequest(AddProviderRequest):
    pass


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    available_models: list[str] | None = None
    is_default: bool | None = None
    extra_headers: dict[str, str] | None = None
    enable_prompt_cache: bool | None = None
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    extra_body: dict[str, Any] | None = None
    enabled: bool | None = None
    roles: str | None = None


class ProviderListResponse(BaseModel):
    items: list[ProviderResponse] = Field(default_factory=list)


class ProviderDeleteResponse(BaseModel):
    ok: bool
    message: str


class ProviderTestResponse(TestConnectionResponse):
    pass


class ProviderDefaultResponse(BaseModel):
    ok: bool
    provider: ProviderResponse


__all__ = [
    "AddProviderRequest",
    "DetectModelsRequest",
    "DetectModelsResponse",
    "ProviderResponse",
    "TestConnectionResponse",
    "ProviderCreateRequest",
    "ProviderUpdateRequest",
    "ProviderListResponse",
    "ProviderDeleteResponse",
    "ProviderTestResponse",
    "ProviderDefaultResponse",
]
