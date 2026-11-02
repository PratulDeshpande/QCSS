"""Cosmic-ray / ionizing quasiparticle burst model."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Recent arrival times kept for inspection; older ones are dropped so a long-running chip (and its
# saved state) does not grow without limit.
MAX_ARRIVAL_HISTORY = 1000


@dataclass
class Burst:
    t0_s: float
    xy_mm: np.ndarray
    peak_gamma_per_us: float


@dataclass
class BurstModel:
    """Poisson QP bursts (McEwen 2022; Li 2025; Harrington 2025)."""
    chip_area_cm2: float
    rng: np.random.Generator
    chip_size_mm: float = 10.0
    impact_rate_per_cm2_s: float = 0.035
    tau_rise_s: float = 10e-6
    spread_time_s: float = 1e-3
    tau_rec_s: float = 25e-3
    sigma0_mm: float = 1.0
    peak_gamma_range_per_us: tuple[float, float] = (0.05, 2.0)
    events: list[Burst] = field(default_factory=list)
    arrival_times_s: list[float] = field(default_factory=list)
    _next_s: float | None = None

    @property
    def rate_hz(self) -> float:
        return self.impact_rate_per_cm2_s * self.chip_area_cm2

    def advance_to(self, t_s: float) -> None:
        if self._next_s is None:
            self._next_s = float(self.rng.exponential(1.0 / self.rate_hz))
        while self._next_s <= t_s:
            xy = self.rng.uniform(0, self.chip_size_mm, size=2)
            peak = float(np.exp(self.rng.uniform(*np.log(self.peak_gamma_range_per_us))))
            self.events.append(Burst(self._next_s, xy, peak))
            self.arrival_times_s.append(self._next_s)
            self._next_s += float(self.rng.exponential(1.0 / self.rate_hz))
        if len(self.arrival_times_s) > MAX_ARRIVAL_HISTORY:
            del self.arrival_times_s[:-MAX_ARRIVAL_HISTORY]
        self.events = [e for e in self.events if t_s - e.t0_s < 10 * self.tau_rec_s]

    def extra_gamma1_per_us(self, t_s: float, qubit_xy_mm: np.ndarray) -> np.ndarray:
        out = np.zeros(len(qubit_xy_mm))
        for e in self.events:
            age = t_s - e.t0_s
            if age < 0:
                continue
            sigma2 = min(self.sigma0_mm**2 + (self.chip_size_mm**2) * min(age / self.spread_time_s, 1.0),
                         self.chip_size_mm**2)
            r2 = np.sum((qubit_xy_mm - e.xy_mm) ** 2, axis=1)
            temporal = (1 - np.exp(-age / self.tau_rise_s)) * np.exp(-age / self.tau_rec_s)
            out += e.peak_gamma_per_us * np.exp(-r2 / (2 * sigma2)) * temporal
        return out
