# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Client-side request throttling."""

import threading
import time
from collections.abc import Callable


class Throttle:
    """Token bucket: at most ``rate`` requests per second on average, with
    bursts of up to ``burst``.

    ``acquire()`` blocks until a request may go. Safe to share between
    threads; callers are served in the order they asked, each told how long
    to wait for its own slot.
    """

    def __init__(
        self,
        rate: float,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.burst = float(burst if burst is not None else max(1, int(rate)))
        if self.burst < 1:
            raise ValueError("burst must be at least 1")

        self._clock = clock
        self._sleep = sleep
        self._tokens = self.burst
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Wait for a slot. Returns the seconds waited."""
        with self._lock:
            now = self._clock()
            self._tokens = min(
                self.burst, self._tokens + (now - self._last) * self.rate
            )
            self._last = now
            self._tokens -= 1.0
            # Negative means the slot is in the future; the debt is paid by
            # time passing, so the next caller's slot is after this one's.
            wait = max(0.0, -self._tokens / self.rate)

        if wait:
            self._sleep(wait)
        return wait
