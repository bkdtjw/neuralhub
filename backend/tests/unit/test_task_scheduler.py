"""Unit tests for the scheduled task system."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import backend.config.redis_client as redis_client

from backend.config.settings import settings
from backend.core.s07_task_system import (
    TaskExecutionError,
    TaskExecutionResult,
    TaskExecutor,
    TaskExecutorDeps,
)
from backend.core.s07_task_system.models import (
    NotifyConfig,
    OutputConfig,
    ScheduledTask,
)
from backend.core.s07_task_system.scheduler import TaskScheduler

from .redis_test_support import use_fake_redis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BEIJING = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
async def _init_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)


def _make_task(**overrides) -> ScheduledTask:
    defaults = dict(
        name="test_task",
        cron="0 7 * * *",
        timezone="Asia/Shanghai",
        prompt="say hello",
        notify=NotifyConfig(feishu=False),
        output=OutputConfig(save_markdown=False),
    )
    defaults.update(overrides)
    return ScheduledTask(**defaults)


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}

    async def list_tasks(self) -> list[ScheduledTask]:
        return [task.model_copy(deep=True) for task in self._tasks.values()]

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        return task.model_copy(deep=True) if task is not None else None

    async def add_task(self, task: ScheduledTask) -> ScheduledTask:
        stored = task.model_copy(deep=True)
        self._tasks[stored.id] = stored
        return stored.model_copy(deep=True)

    async def update_task(self, task_id: str, **kwargs: object) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        updated = task.model_copy(
            update={key: value for key, value in kwargs.items() if value is not None},
            deep=True,
        )
        self._tasks[task_id] = updated
        return updated.model_copy(deep=True)

    async def remove_task(self, task_id: str) -> bool:
        return self._tasks.pop(task_id, None) is not None

    async def update_run_status(self, task_id: str, status: str, output: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.last_run_at = datetime.now()
        task.last_run_status = status
        task.last_run_output = output


async def _temp_store(_tmp_path: Path) -> InMemoryTaskStore:
    return InMemoryTaskStore()


# ---------------------------------------------------------------------------
# Test 1: TaskStore CRUD
# ---------------------------------------------------------------------------


class TestTaskStore:
    @pytest.mark.asyncio
    async def test_add_and_list(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        tasks = await store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == task.id
        assert tasks[0].name == "test_task"

    @pytest.mark.asyncio
    async def test_get_task(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        found = await store.get_task(task.id)
        assert found is not None
        assert found.name == "test_task"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        assert await store.get_task("nonexistent") is None

    @pytest.mark.asyncio
    async def test_update_task(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        updated = await store.update_task(task.id, name="renamed", cron="0 8 * * *")
        assert updated is not None
        assert updated.name == "renamed"
        assert updated.cron == "0 8 * * *"

    @pytest.mark.asyncio
    async def test_update_task_not_found(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        assert await store.update_task("nonexistent", name="x") is None

    @pytest.mark.asyncio
    async def test_remove_task(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        assert await store.remove_task(task.id) is True
        assert await store.get_task(task.id) is None

    @pytest.mark.asyncio
    async def test_remove_task_not_found(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        assert await store.remove_task("nonexistent") is False

    @pytest.mark.asyncio
    async def test_update_run_status(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        await store.update_run_status(task.id, "success", "done")
        found = await store.get_task(task.id)
        assert found.last_run_status == "success"
        assert found.last_run_output == "done"
        assert found.last_run_at is not None


# ---------------------------------------------------------------------------
# Test 2: Cron matching
# ---------------------------------------------------------------------------


class TestCronMatching:
    @pytest.mark.asyncio
    async def test_cron_match_7am(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 7 * * *")
        now = datetime(2026, 1, 1, 7, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is True

    @pytest.mark.asyncio
    async def test_cron_no_match_7_01(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 7 * * *")
        now = datetime(2026, 1, 1, 7, 1, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is False

    @pytest.mark.asyncio
    async def test_cron_monday_9am(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 9 * * 1")
        # 2026-01-05 is a Monday
        now = datetime(2026, 1, 5, 9, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is True

    @pytest.mark.asyncio
    async def test_cron_tuesday_no_match(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 9 * * 1")
        # 2026-01-06 is a Tuesday
        now = datetime(2026, 1, 6, 9, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sec", [0, 1, 2, 15, 30, 45, 59])
    async def test_cron_fires_within_entire_minute(self, tmp_path: Path, sec: int) -> None:
        """30s轮询间隔下，检查可能在分钟内的任意秒数到达，都应触发。"""
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="30 21 * * *")
        now = datetime(2026, 4, 10, 21, 30, sec, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is True

    @pytest.mark.asyncio
    async def test_cron_no_match_next_minute(self, tmp_path: Path) -> None:
        """cron 分钟过后不应再触发。"""
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="30 21 * * *")
        now = datetime(2026, 4, 10, 21, 31, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now) is False


# ---------------------------------------------------------------------------
# Test 3: Timezone correctness
# ---------------------------------------------------------------------------


class TestTimezone:
    @pytest.mark.asyncio
    async def test_utc_23_matches_beijing_7(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 7 * * *", timezone="Asia/Shanghai")
        # UTC 23:00 = Beijing 07:00
        now_beijing = datetime(2026, 1, 1, 7, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now_beijing) is True

    @pytest.mark.asyncio
    async def test_utc_7_no_match(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 7 * * *", timezone="Asia/Shanghai")
        # UTC 07:00 = Beijing 15:00 — should NOT match
        now_beijing = datetime(2026, 1, 1, 15, 0, tzinfo=_BEIJING)
        assert await scheduler._should_run(task, now_beijing) is False


# ---------------------------------------------------------------------------
# Test 5: Task execution timeout
# ---------------------------------------------------------------------------


class TestTaskExecution:
    @pytest.mark.asyncio
    async def test_execution_timeout(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)

        async def slow_execute(t: ScheduledTask) -> str:
            await asyncio.sleep(600)
            return "done"

        executor = MagicMock(spec=TaskExecutor)
        executor.execute = slow_execute
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        with patch("backend.core.s07_task_system.scheduler.asyncio.wait_for") as mock_wait:
            async def _timeout(awaitable: object, timeout: float) -> str:
                if hasattr(awaitable, "close"):
                    awaitable.close()  # type: ignore[call-arg]
                raise asyncio.TimeoutError

            mock_wait.side_effect = _timeout
            await scheduler._run_task(task)

        found = await store.get_task(task.id)
        assert found.last_run_status == "error"
        assert "timed out" in found.last_run_output.lower()


# ---------------------------------------------------------------------------
# Test 6: Scheduler start/stop
# ---------------------------------------------------------------------------


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._running is False
        assert scheduler._task is None


# ---------------------------------------------------------------------------
# Test 7: Tool-based task creation
# ---------------------------------------------------------------------------


class TestTaskTools:
    @pytest.mark.asyncio
    async def test_add_scheduled_task_tool(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        from backend.core.s02_tools.builtin.task_scheduler import create_task_tools

        tools = create_task_tools(store, scheduler, executor)
        tools_map = {t[0].name: t for t in tools}

        add_def, add_exec = tools_map["add_scheduled_task"]
        result = await add_exec({
            "name": "推特AI日报",
            "cron": "0 7 * * *",
            "prompt": "search twitter and summarize",
            "notify_feishu": True,
        })
        assert result.is_error is False
        assert "推特AI日报" in result.output

        tasks = await store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].name == "推特AI日报"

    @pytest.mark.asyncio
    async def test_list_scheduled_tasks_tool(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        await store.add_task(_make_task(name="task1"))
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        from backend.core.s02_tools.builtin.task_scheduler import create_task_tools

        tools = create_task_tools(store, scheduler, executor)
        tools_map = {t[0].name: t for t in tools}

        _, list_exec = tools_map["list_scheduled_tasks"]
        result = await list_exec({})
        assert "task1" in result.output

    @pytest.mark.asyncio
    async def test_remove_scheduled_task_tool(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        from backend.core.s02_tools.builtin.task_scheduler import create_task_tools

        tools = create_task_tools(store, scheduler, executor)
        tools_map = {t[0].name: t for t in tools}

        _, remove_exec = tools_map["remove_scheduled_task"]
        result = await remove_exec({"task_id": task.id})
        assert result.is_error is False
        assert await store.get_task(task.id) is None


# ---------------------------------------------------------------------------
# Test 8: Dedup (no double-execution within same minute)
# ---------------------------------------------------------------------------


class TestDedup:
    @pytest.mark.asyncio
    async def test_no_duplicate_within_minute(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        executor.execute = AsyncMock(return_value="ok")
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        task = _make_task(cron="0 7 * * *")
        now = datetime(2026, 1, 1, 7, 0, tzinfo=_BEIJING)

        assert await scheduler._should_run(task, now) is True
        assert await scheduler._should_run(task, now) is False

    @pytest.mark.asyncio
    async def test_should_run_uses_redis_for_dedup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        fake = await use_fake_redis(monkeypatch)
        task = _make_task(cron="0 7 * * *")
        now = datetime(2026, 1, 1, 7, 0, tzinfo=_BEIJING)

        assert await scheduler._should_run(task, now) is True
        assert await scheduler._should_run(task, now) is False
        assert await fake.client.ttl(f"task:trigger:{task.id}:202601010700") == 120

    @pytest.mark.asyncio
    async def test_should_run_skips_when_redis_unavailable(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        task = _make_task(cron="0 7 * * *")
        now = datetime(2026, 1, 1, 7, 0, tzinfo=_BEIJING)
        settings.redis_url = ""
        await redis_client.close_redis()

        assert await scheduler._should_run(task, now) is False

    @pytest.mark.asyncio
    async def test_execute_task_sets_running_key_in_redis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        fake = await use_fake_redis(monkeypatch)

        async def _execute(_: ScheduledTask) -> str:
            assert await fake.client.exists(f"task:running:{task.id}") == 1
            return "ok"

        executor = MagicMock(spec=TaskExecutor)
        executor.execute = AsyncMock(side_effect=_execute)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        await scheduler._execute_task(task, None)

        assert await fake.client.exists(f"task:running:{task.id}") == 0

    @pytest.mark.asyncio
    async def test_execute_task_records_preview_with_report_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        await use_fake_redis(monkeypatch)
        executor = object.__new__(TaskExecutor)
        executor.execute_with_result = AsyncMock(
            return_value=TaskExecutionResult(
                content="x" * 600,
                report_path="reports/scheduled_tasks/task.md",
            )
        )
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        await scheduler._execute_task(task, None)

        saved = await store.get_task(task.id)
        assert saved is not None
        assert saved.last_run_status == "success"
        assert "完整输出: reports/scheduled_tasks/task.md" in saved.last_run_output
        assert "已截断: 显示前 500 / 600 字符" in saved.last_run_output

    @pytest.mark.asyncio
    async def test_execute_task_running_key_blocks_concurrent_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        fake = await use_fake_redis(monkeypatch)
        await fake.client.set(f"task:running:{task.id}", "other-worker", ex=600)
        executor = MagicMock(spec=TaskExecutor)
        executor.execute = AsyncMock(return_value="ok")
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        await scheduler._execute_task(task, None)

        executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_task_marks_error_when_executor_raises_task_execution_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task()
        await store.add_task(task)
        await use_fake_redis(monkeypatch)
        executor = MagicMock(spec=TaskExecutor)
        executor.execute = AsyncMock(side_effect=TaskExecutionError("boom"))
        scheduler = TaskScheduler(store, executor, check_interval=30.0)

        await scheduler._execute_task(task, None)

        saved = await store.get_task(task.id)
        assert saved is not None
        assert saved.last_run_status == "error"
        assert saved.last_run_output == "boom"

    @pytest.mark.asyncio
    async def test_recover_missed_tasks_triggers_overdue_task(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        now = datetime.now(timezone.utc)
        task = _make_task(cron="0 * * * *", last_run_at=now - timedelta(hours=2))
        await store.add_task(task)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        scheduler._execute_task = AsyncMock()  # type: ignore[method-assign]

        await scheduler._recover_missed_tasks()

        assert scheduler._execute_task.await_count == 1  # type: ignore[attr-defined]
        recovered_task = scheduler._execute_task.await_args.args[0]  # type: ignore[attr-defined]
        assert recovered_task.id == task.id

    @pytest.mark.asyncio
    async def test_recover_missed_tasks_skips_never_run_tasks(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        task = _make_task(last_run_at=None)
        await store.add_task(task)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        scheduler._execute_task = AsyncMock()  # type: ignore[method-assign]

        await scheduler._recover_missed_tasks()

        scheduler._execute_task.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_recover_missed_tasks_skips_disabled_tasks(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        now = datetime.now(timezone.utc)
        task = _make_task(enabled=False, last_run_at=now - timedelta(hours=2))
        await store.add_task(task)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        scheduler._execute_task = AsyncMock()  # type: ignore[method-assign]

        await scheduler._recover_missed_tasks()

        scheduler._execute_task.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_recover_missed_tasks_skips_up_to_date_tasks(self, tmp_path: Path) -> None:
        store = await _temp_store(tmp_path)
        now = datetime.now(timezone.utc)
        task = _make_task(cron="0 * * * *", last_run_at=now)
        await store.add_task(task)
        executor = MagicMock(spec=TaskExecutor)
        scheduler = TaskScheduler(store, executor, check_interval=30.0)
        scheduler._execute_task = AsyncMock()  # type: ignore[method-assign]

        await scheduler._recover_missed_tasks()

        scheduler._execute_task.assert_not_awaited()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 4: Task executor (mocked)
# ---------------------------------------------------------------------------


class TestTaskExecutor:
    @pytest.mark.asyncio
    async def test_execute_calls_adapter(self) -> None:
        mock_adapter = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "execution result"
        mock_response.tool_calls = None
        mock_response.provider_metadata = {}
        mock_adapter.complete.return_value = mock_response

        mock_pm = AsyncMock()
        mock_pm.list_all.return_value = [MagicMock(id="p1", is_default=True)]
        mock_pm.get_adapter.return_value = mock_adapter

        mock_mcp = MagicMock()
        mock_mcp.list_servers.return_value = []

        executor = TaskExecutor(
            TaskExecutorDeps.model_construct(provider_manager=mock_pm, mcp_manager=mock_mcp)
        )
        task = _make_task(
            notify=NotifyConfig(feishu=False),
            output=OutputConfig(save_markdown=False),
        )
        with patch(
            "backend.core.s07_task_system.executor.register_builtin_tools"
        ), patch(
            "backend.core.s07_task_system.executor.MCPToolBridge.sync_all",
            new_callable=AsyncMock,
        ), patch(
            "backend.core.s07_task_system.executor.AgentLoop.run",
            new_callable=AsyncMock,
            return_value=mock_response,
        ), patch(
            "backend.core.s07_task_system.executor.TaskExecutor._save_report",
            new_callable=AsyncMock,
            return_value=Path("/tmp/report.md"),
        ), patch(
            "backend.core.s07_task_system.executor.TaskExecutor._persist_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.core.s07_task_system.executor.build_system_prompt",
            return_value="system",
        ):
            result = await executor.execute(task)
        assert result == "execution result"

    @pytest.mark.asyncio
    async def test_execute_raises_when_agent_run_fails(self) -> None:
        mock_pm = AsyncMock()
        mock_pm.list_all.return_value = [MagicMock(id="p1", is_default=True)]
        mock_pm.get_adapter.return_value = AsyncMock()

        mock_mcp = MagicMock()
        mock_mcp.list_servers.return_value = []

        executor = TaskExecutor(
            TaskExecutorDeps.model_construct(provider_manager=mock_pm, mcp_manager=mock_mcp)
        )
        task = _make_task(
            notify=NotifyConfig(feishu=False),
            output=OutputConfig(save_markdown=False),
        )
        with patch(
            "backend.core.s07_task_system.executor.register_builtin_tools"
        ), patch(
            "backend.core.s07_task_system.executor.MCPToolBridge.sync_all",
            new_callable=AsyncMock,
        ), patch(
            "backend.core.s07_task_system.executor.AgentLoop.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ), patch(
            "backend.core.s07_task_system.executor.TaskExecutor._save_report",
            new_callable=AsyncMock,
            return_value=Path("/tmp/report.md"),
        ), patch(
            "backend.core.s07_task_system.executor.TaskExecutor._persist_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.core.s07_task_system.executor.build_system_prompt",
            return_value="system",
        ):
            with pytest.raises(TaskExecutionError, match="boom"):
                await executor.execute(task)

    @pytest.mark.asyncio
    async def test_execute_uses_agent_runtime_when_spec_id_present(self) -> None:
        mock_loop = AsyncMock()
        mock_loop._config = MagicMock(provider="provider-1", model="model-1")
        mock_loop.messages = []
        mock_result = MagicMock(content="spec result")
        mock_loop.run = AsyncMock(return_value=mock_result)

        runtime = AsyncMock()
        runtime.create_loop_from_id = AsyncMock(return_value=mock_loop)
        provider_manager = AsyncMock()
        provider_manager.get_adapter = AsyncMock(return_value=AsyncMock())

        executor = TaskExecutor(
            TaskExecutorDeps.model_construct(
                provider_manager=provider_manager,
                mcp_manager=AsyncMock(),
                agent_runtime=runtime,
            )
        )
        task = _make_task(spec_id="daily-ai-news", prompt="hello")

        with patch(
            "backend.core.s07_task_system.executor.TaskExecutor._save_report",
            new_callable=AsyncMock,
            return_value=Path("/tmp/report.md"),
        ), patch(
            "backend.core.s07_task_system.executor.TaskExecutor._persist_session",
            new_callable=AsyncMock,
        ):
            result = await executor.execute(task)

        assert result == "spec result"
        runtime.create_loop_from_id.assert_called_once_with(
            "daily-ai-news",
            workspace=str(Path.cwd()),
            session_id=f"scheduled-task:{task.id}",
            task_queue=None,
            checkpoint_fn=ANY,
        )
        # 执行器给 run 输入前置"今天是…(北京时间)"日期横幅(防模型凭记忆写错年份/日期)，
        # 故只断言调用一次且输入以真实 prompt 结尾，不锁死动态日期前缀。
        mock_loop.run.assert_called_once()
        assert mock_loop.run.call_args.args[0].endswith("hello")
