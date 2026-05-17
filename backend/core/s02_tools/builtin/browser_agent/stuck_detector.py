from __future__ import annotations

import hashlib
from collections import deque


class StuckDetector:
    def __init__(self, window: int = 3, screenshot_hash_threshold: int = 3) -> None:
        self.window = window
        self.screenshot_hash_threshold = screenshot_hash_threshold
        self.url_history: deque[str] = deque(maxlen=window)
        self.screenshot_hash_history: deque[str] = deque(maxlen=screenshot_hash_threshold)
        self.action_kind_history: deque[str] = deque(maxlen=window)

    def is_stuck(self, url: str, screenshot: bytes, last_action_kind: str) -> bool:
        if not last_action_kind:
            return False
        self.url_history.append(url)
        self.screenshot_hash_history.append(hashlib.sha256(screenshot).hexdigest()[:16])
        self.action_kind_history.append(last_action_kind)
        if len(self.url_history) < self.window:
            return False
        return (
            len(set(self.url_history)) == 1
            and len(set(self.screenshot_hash_history)) == 1
            and len(set(self.action_kind_history)) == 1
        )


__all__ = ["StuckDetector"]
