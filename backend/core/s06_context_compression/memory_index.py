from __future__ import annotations

from .long_term_memory import LongTermMemory, MemoryEntry


class MemoryIndex:
    def __init__(self, store: LongTermMemory) -> None:
        self._store = store

    def match(self, query: str, *, limit: int = 5) -> list[MemoryEntry]:
        normalized = query.lower()
        scored = [
            (_score(entry, normalized), entry)
            for entry in self._store.entries
            if entry.keywords
        ]
        matches = [item for item in scored if item[0] > 0]
        matches.sort(key=lambda item: (item[0], item[1].hit_count), reverse=True)
        selected = [entry for _, entry in matches[:limit]]
        for entry in selected:
            entry.hit_count += 1
        return selected

    def add(self, entry: MemoryEntry) -> None:
        self._store.entries.append(entry)

    @property
    def store(self) -> LongTermMemory:
        return self._store


def _score(entry: MemoryEntry, query: str) -> float:
    hits = sum(1 for keyword in entry.keywords if keyword.lower() in query)
    if hits <= 0:
        return 0.0
    return hits / max(1, len(entry.keywords)) + min(entry.hit_count, 20) * 0.01
