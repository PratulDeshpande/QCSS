"""Scenario overrides on the hidden device state, set through the admin channel only.

They model what happens to a real chip (a qubit lost to a defect, a frequency jump, a
TLS drifting into resonance, a cosmic-ray hit). Nothing here is visible to a lab client:
it only changes the physics that its measurements see.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from qcss.device.tls import TLSDefect

DEAD_T1_NS = 100.0             # a lost qubit: decays within ~100 ns ...
DEAD_SHIFT_GHZ = -0.2          # ... and sits 200 MHz below where it was calibrated
BURST_TAU_REC_S = 25e-3        # quasiparticle recovery time (McEwen 2022), as in BurstModel


@dataclass
class InjectedBurst:
    row: int                   # device.qubits index of the hit qubit
    t0_s: float
    peak_gamma_per_us: float


@dataclass
class Scenarios:
    n_qubits: int
    frozen: bool = False
    dead: set[int] = field(default_factory=set)
    f_offset_ghz: list[float] = field(default_factory=list)
    t1_factor: list[float] = field(default_factory=list)
    tls: list[tuple[int, TLSDefect]] = field(default_factory=list)
    bursts: list[InjectedBurst] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.f_offset_ghz = self.f_offset_ghz or [0.0] * self.n_qubits
        self.t1_factor = self.t1_factor or [1.0] * self.n_qubits

    def apply(self, row: int, f_ghz: float, t1_ns: float, t_s: float) -> tuple[float, float]:
        """The qubit's (f01 GHz, T1 ns) with every override applied."""
        f = f_ghz + self.f_offset_ghz[row]
        gamma_per_us = 1e3 / (t1_ns * self.t1_factor[row])
        for r, d in self.tls:
            if r == row:
                det_mhz = 1e3 * (f - d.f_ghz)
                gamma_per_us += 2 * math.pi * 2 * d.g_mhz**2 * d.gamma_mhz / (d.gamma_mhz**2 + det_mhz**2)
        for b in self.bursts:
            age = t_s - b.t0_s
            if b.row == row and age >= 0:
                gamma_per_us += b.peak_gamma_per_us * math.exp(-age / BURST_TAU_REC_S)
        t1 = 1e3 / gamma_per_us
        if row in self.dead:
            return f + DEAD_SHIFT_GHZ, min(t1, DEAD_T1_NS)
        return f, t1

    def forget_old_bursts(self, t_s: float) -> None:
        self.bursts = [b for b in self.bursts if t_s - b.t0_s < 40 * BURST_TAU_REC_S]
