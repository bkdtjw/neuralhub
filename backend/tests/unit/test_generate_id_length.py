from __future__ import annotations

import ast
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from backend.common.types.message import generate_id
from backend.storage.models import MessageRecord

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260708_0007_widen_messages_id_to_varchar64.py"
)
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存/元数据单测，跳过 PostgresContainer 避免拖慢。
    yield


def test_generate_id_is_32_lower_hex() -> None:
    value = generate_id()
    assert len(value) == 32
    assert _HEX32.match(value) is not None


def test_generate_id_unique_across_calls() -> None:
    assert generate_id() != generate_id()
    ids = {generate_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_message_record_id_column_widened_to_64() -> None:
    # 读 model 元数据，无需 DB：主键列宽必须容纳 32 位新 id 与旧 12 位 id。
    assert MessageRecord.__table__.c.id.type.length == 64


def _migration_assignments() -> dict[str, object]:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)  # 兼作语法正确性校验（alembic 未安装，无法直接 import）
    values: dict[str, object] = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                values[target.id] = node.value.value
    return values


def test_migration_file_exists_and_defines_revisions() -> None:
    assert _MIGRATION_PATH.is_file()
    assignments = _migration_assignments()
    assert assignments.get("revision") == "20260708_0007"
    assert assignments.get("down_revision") == "20260601_0006"
