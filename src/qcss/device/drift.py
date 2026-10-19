"""Slow drift processes: OU process, log-normal T1 drift, 1/f noise."""
from __future__ import annotations

import numpy as np


class OUProcess:
    """Exact Ornstein-Uhlenbeck update for ANY step (Gillespie 1996):
    x <- mu + (x - mu) e^{-dt/tau} + sigma sqrt(1 - e^{-2 dt/tau}) N(0,1)."""

    def __init__(self, mu: float, sigma: float, tau_s: float, rng: np.random.Generator, x0: float | None = None):
        self.mu, self.sigma, self.tau, self.rng = mu, sigma, tau_s, rng
        self.x = mu + sigma * rng.standard_normal() if x0 is None else x0

    def step(self, dt_s: float) -> float:
        if dt_s > 0:
            e = np.exp(-dt_s / self.tau)
            self.x = self.mu + (self.x - self.mu) * e + self.sigma * np.sqrt(max(0.0, 1 - e * e)) * self.rng.standard_normal()
        return self.x


class LogNormalDrift:
    """Positive parameter (e.g. T1): value = base * exp(OU(0, sigma_ln, tau))."""

    def __init__(self, base: float, sigma_ln: float, tau_s: float, rng: np.random.Generator):
        self.base, self.ou = base, OUProcess(0.0, sigma_ln, tau_s, rng)

    def step(self, dt_s: float) -> float:
        return self.base * float(np.exp(self.ou.step(dt_s)))


class OneOverFNoise:
    """~1/f over [f_lo, f_hi]: sum of OU processes, one per decade, equal variance weights."""

    def __init__(self, amplitude: float, f_lo_hz: float, f_hi_hz: float, rng: np.random.Generator):
        n = max(1, int(np.ceil(np.log10(f_hi_hz / f_lo_hz))))
        taus = 1.0 / (2 * np.pi * np.logspace(np.log10(f_lo_hz), np.log10(f_hi_hz), n))
        self.parts = [OUProcess(0.0, amplitude / np.sqrt(n), t, rng) for t in taus]

    def step(self, dt_s: float) -> float:
        return float(sum(p.step(dt_s) for p in self.parts))
