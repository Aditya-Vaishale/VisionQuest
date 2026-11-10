"""Keeps requests under N per rolling minute (NVIDIA free tier is ~40)."""
from __future__ import annotations

import threading
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_per_window: int, window_s: float = 60.0) -> None:
        self._max = max_per_window
        self._window = window_s
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is free, then claim it."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] >= self._window:
                    self._stamps.popleft()
                if len(self._stamps) < self._max:
                    self._stamps.append(now)
                    return
                wait = self._window - (now - self._stamps[0])
            time.sleep(max(wait, 0.01))
