from __future__ import annotations

import asyncio
import time
from pathlib import Path

from backend.common.errors import AgentError

RETENTION_DAYS = 7
GC_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_ROOTS = ("data/artifacts", "data/sessions")


class ArtifactGCError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="ARTIFACT_GC_FAILED", message=message)


def cleanup_expired_artifacts(days: int = RETENTION_DAYS) -> int:
    cutoff = time.time() - days * 24 * 60 * 60
    removed = 0
    for root in DEFAULT_ROOTS:
        removed += _cleanup_root(Path(root), cutoff)
    return removed


async def run_artifact_gc_loop(shutdown_event: asyncio.Event) -> None:
    try:
        while not shutdown_event.is_set():
            cleanup_expired_artifacts()
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=GC_INTERVAL_SECONDS)
            except TimeoutError:
                continue
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001
        raise ArtifactGCError(str(exc)) from exc


def _cleanup_root(root: Path, cutoff: float) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
        elif path.is_dir():
            _remove_empty_dir(path)
    return removed


def _remove_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        return
