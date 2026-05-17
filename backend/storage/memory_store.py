from __future__ import annotations

from pathlib import Path

from backend.common.errors import AgentError
from backend.core.s06_context_compression import LongTermMemory, MemoryEntry

DEFAULT_MEMORY_PATH = "data/memory/experiences.json"


class MemoryStore:
    def __init__(self, path: str = DEFAULT_MEMORY_PATH) -> None:
        self._path = Path(path)

    def load(self) -> LongTermMemory:
        try:
            if not self._path.exists():
                return LongTermMemory()
            return LongTermMemory.model_validate_json(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AgentError("MEMORY_STORE_LOAD_ERROR", str(exc)) from exc

    def save(self, memory: LongTermMemory) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(memory.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            raise AgentError("MEMORY_STORE_SAVE_ERROR", str(exc)) from exc

    def add(self, entry: MemoryEntry) -> LongTermMemory:
        memory = self.load()
        memory.entries.append(entry)
        self.save(memory)
        return memory
