"""Sequencer and feedback timing jitter in integer ticks."""
from __future__ import annotations

import numpy as np


class TimingJitter:
    """Draws feedback and sequencer execution jitter in integer clock ticks."""

    def __init__(self, jitter_std_ticks: float = 1.0, rng: np.random.Generator | None = None) -> None:
        self.std = float(max(0.0, jitter_std_ticks))
        self.rng = rng if rng is not None else np.random.default_rng()

    def sample_ticks(self) -> int:
        """Sample integer jitter in ticks from a normal distribution with mean 0."""
        if self.std <= 0.0:
            return 0
        return round(float(self.rng.normal(0.0, self.std)))
