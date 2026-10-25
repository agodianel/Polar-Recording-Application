"""Measures the live sample rate of a packetized stream."""

import time
from collections import deque
from typing import Optional


class RateMeter:
    """Sliding-window sample rate from packet arrival times.

    Counting samples per fixed 1 s bin is too coarse for packetized streams
    (a 73-sample ECG packet every ~0.56 s gives 73 or 146 per second), so the
    rate is computed between the first and last packet in the window.
    """

    def __init__(self, window_sec: float = 5.0):
        self.window_sec = window_sec
        self._events: deque[tuple[float, int]] = deque()
        self._last_time: Optional[float] = None

    def reset(self) -> None:
        self._events.clear()
        self._last_time = None

    def add(self, n_samples: int) -> None:
        now = time.monotonic()
        self._events.append((now, n_samples))
        self._last_time = now
        self._trim(now)

    def rate(self) -> Optional[float]:
        """Samples per second, or None if there isn't enough data yet."""
        self._trim(time.monotonic())
        if len(self._events) < 2:
            return None
        elapsed = self._events[-1][0] - self._events[0][0]
        if elapsed <= 0:
            return None
        # The first packet's samples were collected before the window started
        return sum(n for _, n in list(self._events)[1:]) / elapsed

    def seconds_since_last(self) -> Optional[float]:
        if self._last_time is None:
            return None
        return time.monotonic() - self._last_time

    def _trim(self, now: float) -> None:
        while self._events and now - self._events[0][0] > self.window_sec:
            self._events.popleft()
