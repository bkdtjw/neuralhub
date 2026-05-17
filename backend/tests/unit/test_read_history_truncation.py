from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.s02_tools.builtin.read_history import create_read_history_tool


@pytest.mark.asyncio
async def test_read_history_returns_matching_json_fragment_under_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "artifacts" / "sid" / "products.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            [{"item_id": f"item-{index}", "name": "长文本" * 100} for index in range(50)],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, execute = create_read_history_tool()

    result = await execute({"file_path": "data/artifacts/sid/products.json", "query": "item-3"})

    assert result.is_error is False
    assert "item-3" in result.output
    assert len(result.output) <= 2000


@pytest.mark.asyncio
async def test_read_history_supports_json_path_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "sessions" / "sid" / "history.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"items": [{"name": "first"}]}), encoding="utf-8")
    _, execute = create_read_history_tool()

    result = await execute({"file_path": "data/sessions/sid/history.json", "query": ".items[0].name"})

    assert result.output.strip('" \n') == "first"


@pytest.mark.asyncio
async def test_read_history_rejects_paths_outside_history_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "backend.py").write_text("secret", encoding="utf-8")
    _, execute = create_read_history_tool()

    result = await execute({"file_path": "backend.py", "query": "secret"})

    assert result.is_error is True
    assert "data/artifacts" in result.output
