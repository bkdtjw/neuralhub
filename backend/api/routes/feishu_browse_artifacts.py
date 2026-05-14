from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.common.logging import get_logger
from backend.common.types import ToolArtifact
from backend.core.s01_agent_loop import AgentLoop

logger = get_logger(component="feishu_browse_artifacts")


async def send_browse_web_artifacts(handler: Any, chat_id: str, loop: AgentLoop) -> None:
    """Upload current-turn browse_web image artifacts to Feishu, then clean temp files."""
    try:
        for artifact in _current_turn_artifacts(loop):
            await _send_one(handler, chat_id, artifact)
    except Exception as exc:  # noqa: BLE001
        logger.warning("feishu_browse_artifacts_failed", chat_id=chat_id, error=str(exc))


def _current_turn_artifacts(loop: AgentLoop) -> list[ToolArtifact]:
    artifacts: list[ToolArtifact] = []
    for message in reversed(loop.messages):
        if message.role == "user":
            break
        for result in message.tool_results or []:
            for artifact in result.artifacts:
                if artifact.source == "browse_web" and artifact.kind == "image":
                    artifacts.append(artifact)
    return list(reversed(artifacts))


async def _send_one(handler: Any, chat_id: str, artifact: ToolArtifact) -> None:
    path = Path(artifact.path)
    try:
        if not path.exists():
            logger.warning("feishu_browse_artifact_missing", path=str(path))
            return
        image_key = await handler._client.upload_image(path)  # noqa: SLF001
        if not image_key:
            logger.warning("feishu_browse_artifact_upload_failed", path=str(path))
            return
        payload = await handler._client.send_image(chat_id, image_key)  # noqa: SLF001
        if isinstance(payload, dict) and payload.get("code") != 0:
            logger.warning(
                "feishu_browse_artifact_send_failed",
                path=str(path),
                code=payload.get("code"),
                msg=payload.get("msg"),
            )
    finally:
        if artifact.temporary:
            _delete_temp_file(path)


def _delete_temp_file(path: Path) -> None:
    path.unlink(missing_ok=True)
    for parent in path.parents:
        if parent == Path("/tmp") or parent == Path.cwd():
            return
        try:
            parent.rmdir()
        except OSError:
            return


__all__ = ["send_browse_web_artifacts"]
