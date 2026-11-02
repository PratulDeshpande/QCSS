"""Wall-clock pacing of execution: a job takes as long as it would on an instrument.

An instrument first compiles and uploads the program (a log-normal latency), then plays
the shots in real time: shots x (sequence + repetition delay). The simulator computes
faster or slower than that, so the runner reports lab time as it goes and the pacer
waits until wall time has caught up with lab time / time_scale. time_scale 0 means
unpaced (CI). The upload latency is lab time as well, so it scales the same way.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable

import numpy as np

UPLOAD_MEDIAN_S = 0.02        # sequencer compile + upload of a typical job (order of tens of ms)


class PacedRun:
    def __init__(self, scale: Callable[[], float], start_s: float, clock: Callable[[], float]) -> None:
        self._scale, self._start, self._clock = scale, start_s, clock

    async def pace(self, lab_elapsed_s: float, cancel: asyncio.Event) -> None:
        """Return once the job has taken lab_elapsed_s of lab time in wall time (or it is cancelled)."""
        s = self._scale()
        if s <= 0:
            return
        await _wait(self._start + lab_elapsed_s / s - self._clock(), cancel)


class InstrumentPacer:
    def __init__(self, time_scale: Callable[[], float], *, upload_median_s: float = UPLOAD_MEDIAN_S,
                 upload_sigma_ln: float = 0.3, rng: np.random.Generator | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._scale = time_scale
        self._median, self._sigma = upload_median_s, upload_sigma_ln
        self._rng = rng if rng is not None else np.random.default_rng()
        self._clock = clock

    async def begin(self, cancel: asyncio.Event) -> PacedRun:
        """Upload the job (one latency), then start its execution clock."""
        s = self._scale()
        if s > 0 and self._median > 0:
            upload_s = self._median * float(np.exp(self._sigma * self._rng.standard_normal()))
            await _wait(upload_s / s, cancel)
        return PacedRun(self._scale, self._clock(), self._clock)


async def _wait(seconds: float, cancel: asyncio.Event) -> None:
    if seconds > 0 and not cancel.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(cancel.wait(), seconds)
