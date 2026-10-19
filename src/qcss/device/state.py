"""DeviceState: maintains baseline parameters and advances drift, TLS, and bursts on the lab clock.

Without a ``dynamics`` block in the device file every parameter is static, so oracle
devices behave exactly as specified.
"""
from __future__ import annotations

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.device.bursts import BurstModel
from qcss.device.drift import LogNormalDrift, OneOverFNoise
from qcss.device.labclock import LabClock
from qcss.device.tls import TLSBath


class DeviceState:
    def __init__(self, device: DeviceSpec, rng: np.random.Generator, lab_clock: LabClock | None = None) -> None:
        self.device = device
        self.clock = lab_clock if lab_clock is not None else LabClock()
        self.rng = rng
        dyn = device.dynamics
        self.enabled = dyn is not None and dyn.enabled
        if not self.enabled:
            return
        assert dyn is not None
        self.t1_drifts = [LogNormalDrift(q.t1_us, sigma_ln=dyn.t1_sigma_ln, tau_s=dyn.t1_tau_s, rng=rng)
                          for q in device.qubits]
        self.f_noises = [OneOverFNoise(amplitude=dyn.flux_noise_ghz, f_lo_hz=1e-4, f_hi_hz=1e3, rng=rng)
                         for _ in device.qubits]
        self.tls_baths = [TLSBath((q.f_max_ghz - 0.5, q.f_max_ghz + 0.1), n_defects=dyn.tls_per_qubit, rng=rng)
                          for q in device.qubits]
        self.bursts = (BurstModel(chip_area_cm2=device.chip_area_cm2, rng=rng, chip_size_mm=device.chip_side_mm)
                       if dyn.bursts else None)
        self.qubit_coords = np.array([q.xy_mm for q in device.qubits], dtype=np.float64)

    def advance_time(self, dt_s: float) -> None:
        self.clock.advance(dt_s)
        if not self.enabled:
            return
        if self.bursts is not None:
            self.bursts.advance_to(self.clock.t_s)
        for d in self.t1_drifts:
            d.step(dt_s)
        for fn in self.f_noises:
            fn.step(dt_s)
        for tls in self.tls_baths:
            tls.step(dt_s)

    def snapshot(self) -> tuple[list[float], list[float]]:
        """Returns (effective_f01_ghz, effective_t1_ns) at the current lab time."""
        if not self.enabled:
            return [q.f_max_ghz for q in self.device.qubits], [q.t1_us * 1e3 for q in self.device.qubits]
        extra_gamma = (self.bursts.extra_gamma1_per_us(self.clock.t_s, self.qubit_coords)
                       if self.bursts is not None else np.zeros(len(self.device.qubits)))
        eff_f, eff_t1_ns = [], []
        for i, q in enumerate(self.device.qubits):
            f_eff = q.f_max_ghz + self.f_noises[i].step(0.0)
            eff_f.append(f_eff)
            gamma_tot = (1.0 / self.t1_drifts[i].step(0.0) + self.tls_baths[i].extra_gamma1_per_us(f_eff)
                         + float(extra_gamma[i]))
            eff_t1_ns.append(1e3 / gamma_tot)
        return eff_f, eff_t1_ns
