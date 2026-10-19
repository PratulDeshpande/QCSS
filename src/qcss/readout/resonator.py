"""Physical dispersive readout for T2/T3 (one model; error counted once).

Linear resonator per transmon level m:
    d alpha/dt = -(i Delta_m + kappa/2) alpha + sqrt(kappa) A(t),   Delta_m = w_r + dw_r(m) - w_d
    B(t) = -A(t) + sqrt(kappa) alpha(t)                              (reflection)
ADC:  s(t) = G e^{i theta} [ B(t - tau_ToF) + xi(t) ]
Noise: complex white, per-quadrature variance 1/(4 eta dt) per sample
T1 during readout: per-shot exponential jump times; |2> -> |1> at ~2/T1, |1> -> |0> at 1/T1.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ResonatorParams:
    kappa_rad_ns: float               # 2 pi * kappa_MHz * 1e-3
    pulls_rad_ns: tuple[float, ...]   # dw_r(m) for m = 0, 1, 2 (rad/ns)
    drive_detuning_rad_ns: float      # w_r(bare) - w_d
    eta: float                        # measurement efficiency (<= 0.5 phase-preserving amplifier)
    tof_samples: int                  # internal + cable + filter latency, in ADC samples
    gain: float = 1.0
    phase_rad: float = 0.0            # electrical phase
    dt_ns: float = 1.0                # ADC sample period


def drive_amplitude_for_photons(n_bar: float, kappa: float, detuning: float = 0.0) -> float:
    """|A| giving steady-state n_bar at the given drive-resonator detuning."""
    return float(np.sqrt(n_bar * (detuning**2 + kappa**2 / 4.0) / kappa))


class DispersiveReadout:
    def __init__(self, p: ResonatorParams) -> None:
        self.p = p
        self.poles = np.array([-(1j * (p.drive_detuning_rad_ns + d) + p.kappa_rad_ns / 2.0) for d in p.pulls_rad_ns])

    def mean_field(self, level: int, drive: np.ndarray) -> np.ndarray:
        """Exact ZOH solution alpha[k] for a constant level (alpha[0] = 0)."""
        pole = self.poles[level]
        e = np.exp(pole * self.p.dt_ns)
        g = np.sqrt(self.p.kappa_rad_ns) * (e - 1.0) / pole
        alpha = np.zeros(len(drive) + 1, dtype=np.complex128)
        for k, a_k in enumerate(drive):
            alpha[k + 1] = e * alpha[k] + g * a_k
        return alpha[:-1]

    def traces(self, levels0: np.ndarray, drive: np.ndarray, t1_ns: float,
               rng: np.random.Generator, n_th_rate_ns: float = 0.0,
               base: np.ndarray | None = None) -> np.ndarray:
        """Complex ADC traces, shape (shots, len(drive) + tof). Includes T1 jumps and noise.

        `base` = precomputed mean fields per level for this drive (shape (levels, len(drive))).
        """
        p, n = self.p, len(drive)
        if base is None:
            base = np.stack([self.mean_field(m, drive) for m in range(len(p.pulls_rad_ns))])
        alpha = base[levels0].copy()
        rate = {1: 1.0 / t1_ns, 2: 2.0 / t1_ns}               # cascade 2 -> 1 -> 0
        for s, m0 in enumerate(levels0):
            m, k = int(m0), 0
            while m > 0:
                k_jump = k + int(np.ceil(rng.exponential(1.0 / rate[m]) / p.dt_ns))
                if k_jump >= n:
                    break
                m_new = m - 1
                diff = alpha[s, k_jump] - base[m_new, k_jump]
                tail = np.exp(self.poles[m_new] * p.dt_ns * np.arange(n - k_jump))
                alpha[s, k_jump:] = base[m_new, k_jump:] + diff * tail
                m, k = m_new, k_jump
        b = -drive[None, :] + np.sqrt(p.kappa_rad_ns) * alpha
        out = np.zeros((len(levels0), n + p.tof_samples), dtype=np.complex128)
        out[:, p.tof_samples:] = b
        sigma = np.sqrt(1.0 / (4.0 * p.eta * p.dt_ns))
        out += sigma * (rng.standard_normal(out.shape) + 1j * rng.standard_normal(out.shape))
        return p.gain * np.exp(1j * p.phase_rad) * out

    @staticmethod
    def integrate(traces: np.ndarray, weights: np.ndarray, start: int, dt_ns: float,
                  convention: str = "sum") -> np.ndarray:
        """Z = sum_n s[n] conj(w[n]) dt over the acquisition window."""
        win = traces[:, start:start + len(weights)]
        z = win @ np.conj(weights) * dt_ns
        return z / len(weights) if convention == "mean" else z
