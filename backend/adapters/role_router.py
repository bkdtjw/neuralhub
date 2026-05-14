from __future__ import annotations

from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.common.types import ProviderConfig
from backend.config.settings import Settings, settings


class RoleRouter:
    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        settings_obj: Settings | None = None,
    ) -> None:
        self.provider_manager = provider_manager or ProviderManager()
        self._settings = settings_obj or settings

    async def resolve_provider(self, role: str, override_id: str = "") -> ProviderConfig:
        try:
            clean_role = _normalize_role(role)
            providers = await self.provider_manager.list_all()
            target_id = override_id.strip() or _settings_provider_id(self._settings, clean_role)
            if target_id:
                return _find_enabled_provider(providers, target_id)
            for provider in providers:
                if provider.enabled and clean_role in _parse_roles(provider.roles):
                    return provider
            raise AgentError(
                "ROLE_PROVIDER_NOT_FOUND",
                f"No enabled provider configured for role: {clean_role}",
            )
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AgentError("ROLE_PROVIDER_RESOLVE_ERROR", str(exc)) from exc

    async def set_role_default(self, role: str, provider_id: str) -> None:
        try:
            clean_role = _normalize_role(role)
            target_id = provider_id.strip()
            if not target_id:
                raise AgentError("ROLE_PROVIDER_ID_MISSING", "provider_id is required")
            providers = await self.provider_manager.list_all()
            target = _find_enabled_provider(providers, target_id)
            for provider in providers:
                roles = set(_parse_roles(provider.roles))
                before = set(roles)
                if provider.id == target.id:
                    roles.add(clean_role)
                else:
                    roles.discard(clean_role)
                if roles != before:
                    await self.provider_manager.update(provider.id, roles=",".join(sorted(roles)))
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AgentError("ROLE_PROVIDER_SET_ERROR", str(exc)) from exc

    async def get_adapter(self, provider_id: str) -> object:
        try:
            return await self.provider_manager.get_adapter(provider_id)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("ROLE_PROVIDER_ADAPTER_ERROR", str(exc)) from exc


def _normalize_role(role: str) -> str:
    clean = role.strip().lower()
    if not clean or "," in clean:
        raise AgentError("ROLE_INVALID", f"Invalid provider role: {role}")
    return "text" if clean in {"main", "main_agent"} else clean


def _settings_provider_id(settings_obj: Settings, role: str) -> str:
    if role == "vision":
        return settings_obj.vision_subagent_provider_id.strip()
    if role == "text":
        return settings_obj.main_agent_provider_id.strip()
    return ""


def _parse_roles(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _find_enabled_provider(providers: list[ProviderConfig], provider_id: str) -> ProviderConfig:
    provider = next((item for item in providers if item.id == provider_id), None)
    if provider is None:
        raise AgentError("PROVIDER_NOT_FOUND", f"Provider not found: {provider_id}")
    if not provider.enabled:
        raise AgentError("PROVIDER_DISABLED", f"Provider is disabled: {provider_id}")
    return provider


__all__ = ["RoleRouter"]
