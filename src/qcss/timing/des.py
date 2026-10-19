"""Integer-tick discrete-event engine.

Ordering key: (tick, priority, seq). `priority` encodes hardware same-cycle semantics;
`seq` gives FIFO among equal (tick, priority). Plain lists on the heap avoid
dataclass __lt__ overhead; cancellation is lazy.
"""
from __future__ import annotations

import heapq
import itertools
from collections import deque
from collections.abc import Callable
from enum import IntEnum
from typing import Any


class Prio(IntEnum):
    """Same-tick order used by real sequencers (lower runs first)."""
    FRAME_UPDATE = 0       # latched NCO/frame updates take effect
    ACQ_COMPLETE = 1       # integration finishes, result written to register
    BRANCH_DECISION = 2    # condition evaluated
    PLAYBACK = 3           # pulses start
    BOOKKEEPING = 9        # telemetry, end-of-shot


_T, _P, _S, _CB, _ARGS, _DEAD = range(6)


class DES:
    __slots__ = ("_q", "_seq", "now", "trace")

    def __init__(self, now: int = 0, trace_len: int = 0) -> None:
        self.now: int = now
        self._q: list[list[Any]] = []
        self._seq = itertools.count()
        self.trace: deque | None = deque(maxlen=trace_len) if trace_len else None

    def schedule_at(self, tick: int, prio: int, cb: Callable[..., None], *args: Any) -> list[Any]:
        if type(tick) is not int:                    # no silent float truncation
            raise TypeError(f"tick must be int, got {type(tick).__name__}")
        if tick < self.now:
            raise ValueError(f"cannot schedule in the past: {tick} < {self.now}")
        ev = [tick, int(prio), next(self._seq), cb, args, False]
        heapq.heappush(self._q, ev)
        return ev

    def schedule_in(self, delay: int, prio: int, cb: Callable[..., None], *args: Any) -> list[Any]:
        if type(delay) is not int or delay < 0:
            raise ValueError(f"delay must be a non-negative int, got {delay!r}")
        return self.schedule_at(self.now + delay, prio, cb, *args)

    @staticmethod
    def cancel(ev: list[Any]) -> None:
        ev[_DEAD] = True

    def peek_tick(self) -> int | None:
        while self._q and self._q[0][_DEAD]:
            heapq.heappop(self._q)
        return self._q[0][_T] if self._q else None

    def run_until(self, t_end: int | None = None) -> None:
        while self._q and (t_end is None or self._q[0][_T] <= t_end):
            ev = heapq.heappop(self._q)
            if ev[_DEAD]:
                continue
            self.now = ev[_T]
            if self.trace is not None:
                cb = ev[_CB]
                self.trace.append((ev[_T], ev[_P], getattr(cb, "__qualname__", repr(cb))))
            ev[_CB](*ev[_ARGS])
        if t_end is not None and t_end > self.now:
            self.now = t_end                          # clock advances to the horizon
