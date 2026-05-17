from __future__ import annotations

from pathlib import Path

import pytest

from backend.api.routes.feishu_browse_artifacts import send_browse_web_artifacts
from backend.common.types import Message, ToolArtifact, ToolResult


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[Path] = []
        self.sent: list[tuple[str, str]] = []

    async def upload_image(self, path: Path) -> str:
        self.uploads.append(path)
        return "img_key"

    async def send_image(self, chat_id: str, image_key: str) -> dict[str, object]:
        self.sent.append((chat_id, image_key))
        return {"code": 0}


class FakeHandler:
    def __init__(self) -> None:
        self._client = FakeClient()


class FakeLoop:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages


@pytest.mark.asyncio
async def test_sends_current_turn_browse_web_images_and_deletes_temp(tmp_path: Path) -> None:
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(b"png")
    loop = FakeLoop(
        [
            Message(role="user", content="old"),
            Message(
                role="tool",
                content="",
                tool_results=[
                    ToolResult(
                        output="old",
                        artifacts=[
                            ToolArtifact(
                                kind="image",
                                path=str(tmp_path / "old.png"),
                                source="browse_web",
                                temporary=True,
                            )
                        ],
                    )
                ],
            ),
            Message(role="user", content="new"),
            Message(
                role="tool",
                content="",
                tool_results=[
                    ToolResult(
                        output="new",
                        artifacts=[
                            ToolArtifact(
                                kind="image",
                                path=str(image_path),
                                source="browse_web",
                                temporary=True,
                            )
                        ],
                    )
                ],
            ),
            Message(role="assistant", content="done"),
        ]
    )
    handler = FakeHandler()

    await send_browse_web_artifacts(handler, "chat", loop)  # type: ignore[arg-type]

    assert handler._client.uploads == [image_path]
    assert handler._client.sent == [("chat", "img_key")]
    assert image_path.exists() is False
