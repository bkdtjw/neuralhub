from __future__ import annotations

from .models import AgentSpec
from .registry import SpecRegistry


class SkillMatcher:
    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry

    def match(self, user_text: str, *, limit: int = 2) -> list[AgentSpec]:
        normalized = user_text.lower()
        if not normalized:
            return []
        matches: list[AgentSpec] = []
        for spec in self._registry.list_all():
            if spec.mode != "inject":
                continue
            if _matches_spec(spec, normalized):
                matches.append(spec)
            if len(matches) >= limit:
                break
        return matches


def _matches_spec(spec: AgentSpec, text: str) -> bool:
    return any(keyword.lower() in text for keyword in spec.trigger_keywords if keyword)
