from __future__ import annotations

from pydantic import BaseModel

from backend.common.errors import AgentError
from backend.common.types import Message

from .models import AgentSpec
from .registry import SpecRegistry
from .skill_matcher import SkillMatcher


class SkillLoadResult(BaseModel):
    skill_id: str
    mode: str
    injected: bool
    message: str


class OnDemandSkillLoader:
    def __init__(self, registry: SpecRegistry, inject_limit: int = 2) -> None:
        self._registry = registry
        self._matcher = SkillMatcher(registry)
        self._inject_limit = inject_limit
        self._pending: list[AgentSpec] = []

    def match(self, user_text: str) -> list[Message]:
        specs = self._dedupe([*self._pending, *self._matcher.match(user_text)])
        self._pending.clear()
        return [self._message_for_spec(spec) for spec in specs[: self._inject_limit]]

    def load_skill(self, skill_id: str) -> SkillLoadResult:
        spec = self._registry.get(skill_id)
        if spec is None:
            raise AgentError("SKILL_SPEC_NOT_FOUND", f"Skill spec not found: {skill_id}")
        if not spec.enabled:
            raise AgentError("SKILL_SPEC_DISABLED", f"Skill spec is disabled: {skill_id}")
        if spec.mode != "inject":
            return SkillLoadResult(
                skill_id=skill_id,
                mode=spec.mode,
                injected=False,
                message="loop mode skill should be executed through its dedicated AgentLoop.",
            )
        self._message_for_spec(spec)
        self._pending.append(spec)
        return SkillLoadResult(
            skill_id=skill_id,
            mode=spec.mode,
            injected=True,
            message="skill will be injected into Zone 2 on the next LLM request.",
        )

    @staticmethod
    def _dedupe(specs: list[AgentSpec]) -> list[AgentSpec]:
        seen: set[str] = set()
        result: list[AgentSpec] = []
        for spec in specs:
            if spec.id in seen:
                continue
            seen.add(spec.id)
            result.append(spec)
        return result

    @staticmethod
    def _message_for_spec(spec: AgentSpec) -> Message:
        prompt = spec.system_prompt.strip()
        if len(prompt) > spec.inject_max_chars:
            raise AgentError(
                "SKILL_INJECT_PROMPT_TOO_LONG",
                f"Skill {spec.id} inject prompt exceeds {spec.inject_max_chars} chars.",
            )
        return Message(role="system", content=prompt)
