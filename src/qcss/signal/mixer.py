"""IQ-mixer imperfections and LO leakage, applied in the IF frame on the continuous stream.

Complex-baseband model (T. F. Wong, SDR notes 5.2): for m = m_I + j m_Q,
    x = mu * m + nu * conj(m) + d
    mu = (g_I e^{j phi/2} + g_Q e^{-j phi/2}) / 2,   nu = (g_I e^{j phi/2} - g_Q e^{-j phi/2}) / 2
Image-to-signal power ~ ((g-1)^2 + phi^2)/4 for small errors.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class IQImpairment:
    gain_i: float = 1.0
    gain_q: float = 1.0
    phase_rad: float = 0.0
    dc_i: float = 0.0
    dc_q: float = 0.0

    @property
    def mu(self) -> complex:
        return 0.5 * (self.gain_i * np.exp(0.5j * self.phase_rad) + self.gain_q * np.exp(-0.5j * self.phase_rad))

    @property
    def nu(self) -> complex:
        return 0.5 * (self.gain_i * np.exp(0.5j * self.phase_rad) - self.gain_q * np.exp(-0.5j * self.phase_rad))


@dataclass(frozen=True)
class IQCorrection:
    """What the OS programs (Qblox-style: offsets + gain ratio + phase on the digital I/Q)."""
    dc_i: float = 0.0
    dc_q: float = 0.0
    gain_ratio: float = 1.0        # multiplies Q
    phase_rad: float = 0.0         # mixes I into Q

    def apply(self, m: np.ndarray) -> np.ndarray:
        i, q = np.real(m), np.imag(m)
        q2 = self.gain_ratio * (q * np.cos(self.phase_rad) + i * np.sin(self.phase_rad))
        return (i + self.dc_i) + 1j * (q2 + self.dc_q)


def apply_mixer(m_if: np.ndarray, truth: IQImpairment, corr: IQCorrection, lo_enabled: bool = True) -> np.ndarray:
    """m_if: complex DAC stream (already NCO-modulated). Returns the RF complex envelope
    relative to the LO. The DC term is present on EVERY sample while the LO is on."""
    m = corr.apply(m_if)
    x = truth.mu * m + truth.nu * np.conj(m)
    if lo_enabled:
        x = x + (truth.dc_i + 1j * truth.dc_q)
    return x


def to_qubit_frame(x_rf_env: np.ndarray, t_s: np.ndarray, f_lo_hz: float, f_frame_hz: float,
                   line_scale_rad_per_ns: float) -> np.ndarray:
    """Omega_q(t) = scale * x(t) * exp(i 2 pi (f_LO - f_frame) t)."""
    return line_scale_rad_per_ns * x_rf_env * np.exp(2j * np.pi * (f_lo_hz - f_frame_hz) * t_s)
