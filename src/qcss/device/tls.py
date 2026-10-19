"""Two-level fluctuator (TLS) defect bath and spectral diffusion."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TLSDefect:
    f_ghz: float
    g_mhz: float              # coupling 0.05-0.5 MHz (Klimov 2018)
    gamma_mhz: float          # TLS linewidth 0.5-20 MHz
    jump_mhz: float           # telegraph amplitude (up to ~30 MHz)
    switch_rate_hz: float     # log-uniform in [50 uHz, 5 mHz]
    state: int = 0


class TLSBath:
    """Gamma1(f_q) = Gamma_bg + sum_k 2 g_k^2 gamma_k / (gamma_k^2 + (f_q - f_k)^2)."""

    def __init__(self, f_range_ghz: tuple[float, float], n_defects: int, rng: np.random.Generator,
                 diffusion_mhz_per_sqrt_h: float = 2.5) -> None:
        self.rng = rng
        self.D = diffusion_mhz_per_sqrt_h
        lo, hi = f_range_ghz
        self.defects = [TLSDefect(
            f_ghz=float(rng.uniform(lo, hi)),
            g_mhz=float(rng.uniform(0.05, 0.5)),
            gamma_mhz=float(rng.uniform(0.5, 20.0)),
            jump_mhz=float(rng.uniform(1.0, 30.0)),
            switch_rate_hz=float(10 ** rng.uniform(np.log10(5e-5), np.log10(5e-3))),
        ) for _ in range(n_defects)]

    def step(self, dt_s: float) -> None:
        dt_h = dt_s / 3600.0
        for d in self.defects:
            d.f_ghz += 1e-3 * 2 * self.D * np.sqrt(max(0.0, dt_h)) * self.rng.standard_normal()
            n_flips = self.rng.poisson(max(0.0, d.switch_rate_hz * dt_s))
            if n_flips % 2:
                d.state ^= 1

    def extra_gamma1_per_us(self, f_q_ghz: float) -> float:
        tot = 0.0
        for d in self.defects:
            f_eff = d.f_ghz + 1e-3 * d.jump_mhz * d.state
            det_mhz = 1e3 * (f_q_ghz - f_eff)
            tot += 2 * d.g_mhz**2 * d.gamma_mhz / (d.gamma_mhz**2 + det_mhz**2)
        return 2 * np.pi * tot
