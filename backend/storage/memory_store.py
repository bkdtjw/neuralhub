from __future__ import annotations

import os
from pathlib import Path

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.s06_context_compression import LongTermMemory, MemoryEntry

logger = get_logger(component="memory_store")

DEFAULT_MEMORY_PATH = "data/memory/experiences.json"


class MemoryStore:
    def __init__(self, path: str = DEFAULT_MEMORY_PATH) -> None:
        self._path = Path(path)

    def load(self) -> LongTermMemory:
        if not self._path.exists():
            return LongTermMemory()
        try:
            return LongTermMemory.model_validate_json(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("memory_store_load_failed", path=str(self._path), error=str(exc))
            self._quarantine_corrupt_file()
            return LongTermMemory()

    def save(self, memory: LongTermMemory) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(memory.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("MEMORY_STORE_SAVE_ERROR", str(exc)) from exc

    def add(self, entry: MemoryEntry) -> LongTermMemory:
        memory = self.load()
        memory.entries.append(entry)
        self.save(memory)
        return memory

    def _quarantine_corrupt_file(self) -> None:
        corrupt_path = self._path.with_name(f"{self._path.name}.corrupt")
        try:
            os.replace(self._path, corrupt_path)
        except OSError as exc:
            logger.error(
                "memory_store_quarantine_failed", path=str(self._path), error=str(exc)
            )
