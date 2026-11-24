"""Virtual lab clock: advances deterministically per shot and between jobs."""
from __future__ import annotations

import math


class LabClock:
    def __init__(self, t0_s: float = 0.0) -> None:
        self.t_s = t0_s

    def advance(self, dt_s: float) -> None:
        if not math.isfinite(dt_s):
            raise ValueError("lab time step must be finite")
        if dt_s < 0:
            raise ValueError("lab time cannot go backwards")
        self.t_s += dt_s
