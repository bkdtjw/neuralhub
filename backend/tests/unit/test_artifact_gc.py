from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from backend.core.s06_context_compression import artifact_gc

_DAY = 24 * 60 * 60


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


def _age(path: Path, seconds_ago: float) -> None:
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


# --- 容错：单个坏文件不能中断整轮清理 ---


def test_cleanup_root_skips_stat_error_and_removes_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "artifacts"
    (root / "sub").mkdir(parents=True)
    good = root / "sub" / "good.txt"
    bad = root / "sub" / "bad.txt"
    good.write_text("g")
    bad.write_text("b")
    _age(good, 8 * _DAY)
    _age(bad, 8 * _DAY)

    real_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self.name == "bad.txt":
            raise PermissionError("stat denied")  # PermissionError 是 OSError 子类
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    cutoff = time.time() - 7 * _DAY
    removed = artifact_gc._cleanup_root(root, cutoff)  # 断言不抛

    monkeypatch.undo()  # 还原真实 stat，让下面的 exists() 断言不再命中假桩
    assert removed == 1
    assert not good.exists()  # 过期且可 stat → 删除
    assert bad.exists()  # stat 抛错 → 跳过保留，未误删


# --- 保护无损备份：data/sessions 用 90 天保留，artifacts 用 7 天 ---


def test_default_cleanup_protects_sessions_but_expires_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "data" / "artifacts"
    sessions = tmp_path / "data" / "sessions"
    artifacts.mkdir(parents=True)
    sessions.mkdir(parents=True)
    art_file = artifacts / "a.json"
    sess_file = sessions / "s.json"
    art_file.write_text("a")
    sess_file.write_text("s")
    _age(art_file, 8 * _DAY)
    _age(sess_file, 8 * _DAY)

    monkeypatch.setattr(artifact_gc, "DEFAULT_ROOTS", (str(artifacts),))
    monkeypatch.setattr(artifact_gc, "SESSION_ROOT", str(sessions))

    removed = artifact_gc.cleanup_expired_artifacts()

    assert removed == 1
    assert not art_file.exists()  # 7 天保留 → 8 天过期删除
    assert sess_file.exists()  # 90 天保留 → 8 天仍在，L3 无损备份不误删


def test_sessions_removed_from_default_roots() -> None:
    # data/sessions 已从 7 天 GC 中摘出，并有远长于 artifacts 的独立保留期。
    assert artifact_gc.DEFAULT_ROOTS == ("data/artifacts",)
    assert artifact_gc.SESSION_ROOT == "data/sessions"
    assert artifact_gc.SESSION_RETENTION_DAYS > artifact_gc.RETENTION_DAYS


# --- 循环韧性：单轮清理异常不能杀死 GC 循环 ---


@pytest.mark.asyncio
async def test_loop_survives_cleanup_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    event = asyncio.Event()

    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk exploded")  # 第一轮炸掉
        event.set()  # 第二轮：置位 shutdown 让循环干净退出
        return 0

    monkeypatch.setattr(artifact_gc, "cleanup_expired_artifacts", flaky)
    monkeypatch.setattr(artifact_gc, "GC_INTERVAL_SECONDS", 0.01)

    await asyncio.wait_for(artifact_gc.run_artifact_gc_loop(event), timeout=2.0)

    assert calls["n"] >= 2  # 第一轮异常没有中断循环，第二轮仍然执行


# --- API 进程接线：start/stop 幂等且能干净拉起/收敛后台任务 ---


@pytest.mark.asyncio
async def test_start_stop_artifact_gc_wires_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.api import lifespan_support

    # 让后台循环不触碰真实 data/ 目录。
    monkeypatch.setattr(artifact_gc, "cleanup_expired_artifacts", lambda *a, **k: 0)

    app = SimpleNamespace(state=SimpleNamespace())
    lifespan_support.start_artifact_gc(app)
    task = app.state.artifact_gc_task
    assert task is not None and not task.done()

    lifespan_support.start_artifact_gc(app)  # 幂等：不重复启动
    assert app.state.artifact_gc_task is task

    await lifespan_support.stop_artifact_gc(app)
    assert task.done()
    assert app.state.artifact_gc_task is None
    assert app.state.artifact_gc_shutdown is None

    await lifespan_support.stop_artifact_gc(app)  # 无任务时安全的二次调用
