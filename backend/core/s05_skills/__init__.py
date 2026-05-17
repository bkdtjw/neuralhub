from typing import Any

from .loader import SkillLoader
from .mcp_requirements import extract_required_mcp_servers
from .models import AgentCategory, AgentSpec, SubAgentPolicy, ToolConfig
from .on_demand_loader import OnDemandSkillLoader, SkillLoadResult
from .registry import SpecRegistry
from .skill_matcher import SkillMatcher

__all__ = [
    "AgentCategory",
    "AgentSpec",
    "SkillLoader",
    "SpecRegistry",
    "OnDemandSkillLoader",
    "SkillLoadResult",
    "SkillMatcher",
    "SubAgentPolicy",
    "ToolConfig",
    "extract_required_mcp_servers",
    "AgentRuntime",
    "AgentRuntimeDeps",
]


def __getattr__(name: str) -> Any:
    if name in {"AgentRuntime", "AgentRuntimeDeps"}:
        from .runtime import AgentRuntime, AgentRuntimeDeps

        exports = {
            "AgentRuntime": AgentRuntime,
            "AgentRuntimeDeps": AgentRuntimeDeps,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
