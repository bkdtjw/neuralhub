from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import pytest_asyncio

from backend.core.s01_agent_loop import PlanCheckpointStore, PlanPhase, PlanState


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯文件系统单测，跳过 PostgresContainer 避免拖慢。
    yield


def _state(plan_name: str, phase: PlanPhase) -> PlanState:
    return PlanState(plan_name=plan_name, session_id="session-1", phase=phase)


def _age(path: object, days: int) -> None:
    timestamp = time.time() - days * 86400
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_old_terminal_and_corrupt_checkpoints(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    old_done = store.save(_state("old-done", PlanPhase.COMPLETED))
    old_running = store.save(_state("old-running", PlanPhase.EXECUTING))
    fresh_done = store.save(_state("fresh-done", PlanPhase.CANCELLED))
    corrupt = tmp_path / "session-1-corrupt-plan.json"
    tmp = tmp_path / "session-1-tmp-plan.tmp"
    corrupt.write_text("{broken", encoding="utf-8")
    tmp.write_text("{broken", encoding="utf-8")
    for path in (old_done, old_running, corrupt, tmp):
        _age(path, 10)

    removed = store.cleanup(max_age_days=7)

    assert removed == 3
    assert not old_done.exists()
    assert old_running.exists()
    assert fresh_done.exists()
    assert not corrupt.exists()
    assert not tmp.exists()


def test_cleanup_stale_removes_only_old_non_terminal(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    old_running = store.save(_state("old-running", PlanPhase.EXECUTING))
    old_paused = store.save(_state("old-paused", PlanPhase.PAUSED))
    old_done = store.save(_state("old-done", PlanPhase.COMPLETED))
    fresh_running = store.save(_state("fresh-running", PlanPhase.EXECUTING))
    corrupt = tmp_path / "session-1-corrupt-plan.json"
    corrupt.write_text("{broken", encoding="utf-8")
    for path in (old_running, old_paused, old_done, corrupt):
        _age(path, 40)

    removed = store.cleanup_stale(max_stale_days=30)

    assert removed == 2
    assert not old_running.exists()
    assert not old_paused.exists()
    assert old_done.exists()  # 终态：归 cleanup 处理，cleanup_stale 不碰
    assert fresh_running.exists()  # 未超龄：保留以便恢复
    assert corrupt.exists()  # 无法解析：保守跳过，交给 cleanup


def test_cleanup_stale_default_threshold_removes_json_and_backup(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    path = store.save(_state("resumable", PlanPhase.PAUSED))
    backup = path.with_suffix(".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _age(path, 45)
    _age(backup, 45)

    removed = store.cleanup_stale()  # 默认 30 天阈值

    assert removed == 2
    assert not path.exists()
    assert not backup.exists()
