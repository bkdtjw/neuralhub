from __future__ import annotations

import os
import time

from backend.core.s01_agent_loop import PlanCheckpointStore, PlanPhase, PlanState


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
