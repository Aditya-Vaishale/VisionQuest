"""Keeps requests under N per rolling minute (NVIDIA free tier is ~40), spaced out so a
pool of threads cannot send them all in the same instant."""
from __future__ import annotations

import threading
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_per_window: int, window_s: float = 60.0) -> None:
        self._max = max_per_window
        self._window = window_s
        self._gap = window_s / max(max_per_window, 1)   # smallest space between two requests
        self._stamps: deque[float] = deque()
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is free, then claim it. Requests are spaced, never bursted."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] >= self._window:
                    self._stamps.popleft()
                since_last = now - self._last
                full = len(self._stamps) >= self._max
                if not full and since_last >= self._gap:
                    self._stamps.append(now)
                    self._last = now
                    return
                wait = max(self._gap - since_last,
                           self._window - (now - self._stamps[0]) if full else 0.0)
            time.sleep(max(wait, 0.01))
