from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from backend.adapters.role_router import RoleRouter
from backend.common.types import (
    ToolArtifact,
    ToolDefinition,
    ToolExecuteFn,
    ToolParameterSchema,
    ToolResult,
)
from backend.storage.asset_store import AssetStore

from .main_agent_loop import run_browser_agent
from .models import BrowserAgentConfig


def create_browse_web_tool(role_router: RoleRouter) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="browse_web",
        description=(
            "Open a browser and complete a multi-step web task autonomously. "
            "Use for finding info on websites, scraping data behind login, "
            "and interacting with web UIs. Returns text result."
        ),
        category="browser",
        parameters=ToolParameterSchema(
            properties={
                "task": {"type": "string", "description": "High-level task in natural language"},
                "domain": {"type": "string", "description": "Optional storage_state domain"},
                "max_steps": {"type": "integer", "description": "Default 15, max 30"},
                "vision_provider_id": {"type": "string", "description": "Override vision provider"},
                "main_agent_provider_id": {
                    "type": "string",
                    "description": "Override main agent provider",
                },
                "screenshot_policy": {
                    "type": "string",
                    "description": "none or core. Default core sends only final/evidence screenshot.",
                },
            },
            required=["task"],
        ),
    )

    async def execute(args: dict[str, Any]) -> ToolResult:
        try:
            task = str(args.get("task", "")).strip()
            if not task:
                return ToolResult(output="task is required", is_error=True)
            max_steps = min(int(args.get("max_steps", 15) or 15), 30)
            policy = _screenshot_policy(args)
            temp_root = _new_temp_root() if policy == "core" else None
            result = await run_browser_agent(
                BrowserAgentConfig(
                    task=task,
                    domain=str(args.get("domain", "") or ""),
                    max_steps=max_steps,
                    vision_subagent_provider_id=str(args.get("vision_provider_id", "") or ""),
                    main_agent_provider_id=str(args.get("main_agent_provider_id", "") or ""),
                ),
                role_router,
                AssetStore(root=temp_root) if temp_root is not None else None,
            )
            needs_human = result.reason == "need_human"
            output = result.content if result.success or needs_human else f"Browse failed: {result.reason}"
            artifacts = _core_screenshot_artifacts(result.screenshots, result.success, result.reason)
            _delete_non_core_screenshots(result.screenshots, artifacts)
            _cleanup_unused_temp_root(temp_root, artifacts)
            return ToolResult(
                output=output,
                is_error=not result.success and not needs_human,
                diffs=[],
                artifacts=artifacts,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Browse failed: {exc}", is_error=True)

    return definition, execute


def _screenshot_policy(args: dict[str, Any]) -> str:
    value = str(args.get("screenshot_policy", "core") or "core").strip().lower()
    return value if value in {"core", "none"} else "core"


def _new_temp_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="browse_web_"))


def _core_screenshot_artifacts(
    paths: list[Path],
    success: bool,
    reason: str = "",
) -> list[ToolArtifact]:
    if not paths:
        return []
    path = paths[-1]
    return [
        ToolArtifact(
            kind="image",
            path=str(path),
            mime_type="image/png",
            label=_artifact_label(success, reason),
            source="browse_web",
            temporary=True,
        )
    ]


def _artifact_label(success: bool, reason: str) -> str:
    if reason == "need_human":
        return "browse_web_human_required"
    return "browse_web_result" if success else "browse_web_error"


def _delete_non_core_screenshots(paths: list[Path], artifacts: list[ToolArtifact]) -> None:
    keep = {Path(artifact.path) for artifact in artifacts}
    for path in paths[:-1]:
        if path in keep:
            continue
        path.unlink(missing_ok=True)


def _cleanup_unused_temp_root(temp_root: Path | None, artifacts: list[ToolArtifact]) -> None:
    if temp_root is None:
        return
    if any(Path(artifact.path).is_relative_to(temp_root) for artifact in artifacts):
        return
    shutil.rmtree(temp_root, ignore_errors=True)


__all__ = ["create_browse_web_tool"]
