"""Stateful linear filters for continuous per-port sample streams.

Every filter keeps its internal state between calls (zi -> zf), so filtering a stream in
chunks equals filtering it in one call, and filter tails leak into the next pulse / shot
exactly as on hardware (Qblox applies its RTP filters to a continuous data stream).

Physical flux-line model (Rol et al. 2020 / Qblox fit form), step response
    s(t) = g * [1 + sum_k A_k e^{-t/tau_k}] * u(t)       (A_k signed; tau from ns to ms)
Exact discretisation of ONE term as a parallel branch:
    s[n] = 1 + A p^n,  p = e^{-Ts/tau}
    H(z) = 1 + A (1 - z^-1) / (1 - p z^-1) = ((1+A) - (p+A) z^-1) / (1 - p z^-1)
    => s[0] = 1 + A, s[inf] = 1  (DC gain exactly 1).
"""
from __future__ import annotations

import numpy as np
from scipy import signal


class StatefulSOS:
    """Second-order-section IIR with persistent state (scipy.signal.sosfilt + zi)."""

    def __init__(self, sos: np.ndarray) -> None:
        self.sos = np.atleast_2d(np.asarray(sos, dtype=np.float64))
        self.zi = np.zeros((self.sos.shape[0], 2))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = signal.sosfilt(self.sos, np.asarray(x, dtype=np.float64), zi=self.zi)
        return y

    def reset(self) -> None:
        self.zi[:] = 0.0

    def fast_forward_zeros(self, n: int) -> None:
        """Advance state through n zero samples without materialising them (long idles)."""
        if n <= 0 or not np.any(self.zi):
            return
        if n > 4096:                                   # decay is geometric; chunk to bound cost
            for _ in range(n // 4096):
                self(np.zeros(4096))
            n %= 4096
        if n:
            self(np.zeros(n))


class StatefulFIR:
    def __init__(self, taps: np.ndarray) -> None:
        self.b = np.asarray(taps, dtype=np.float64)
        self.zi = np.zeros(max(len(self.b) - 1, 0))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if len(self.b) == 1:
            return self.b[0] * np.asarray(x, dtype=np.float64)
        y, self.zi = signal.lfilter(self.b, [1.0], np.asarray(x, dtype=np.float64), zi=self.zi)
        return y

    def reset(self) -> None:
        self.zi[:] = 0.0


def exp_term_sos(amplitude: float, tau_s: float, fs_hz: float) -> np.ndarray:
    """One Rol-form exponential term as a full first-order section: s[n] = 1 + A p^n."""
    p = np.exp(-1.0 / (tau_s * fs_hz))
    return np.array([[1.0 + amplitude, -(p + amplitude), 0.0, 1.0, -p, 0.0]])


def bias_tee_sos(tau_s: float, fs_hz: float) -> np.ndarray:
    """First-order high-pass with step response p^n (bias-tee droop)."""
    p = np.exp(-1.0 / (tau_s * fs_hz))
    return np.array([[1.0, -1.0, 0.0, 1.0, -p, 0.0]])


def butter_sos(order: int, cutoff_hz: float, fs_hz: float) -> np.ndarray:
    """DAC reconstruction / line low-pass, normalised with the ACTUAL sample rate (fixes SC-01)."""
    return signal.butter(order, cutoff_hz, btype="low", fs=fs_hz, output="sos")


class FluxLineModel:
    """h_phys = gain * prod_k (1 + A_k-term) * bias-tee * FIR(short-time, echoes) * LPF."""

    def __init__(self, fs_hz: float, exp_terms: list[tuple[float, float]], *,
                 bias_tee_tau_s: float | None = None, fir_taps: np.ndarray | None = None,
                 lpf_hz: float | None = None, gain: float = 1.0) -> None:
        sos = [exp_term_sos(a, t, fs_hz) for a, t in exp_terms]
        if bias_tee_tau_s:
            sos.append(bias_tee_sos(bias_tee_tau_s, fs_hz))
        if lpf_hz:
            sos.append(butter_sos(4, lpf_hz, fs_hz))
        self.iir = StatefulSOS(np.vstack(sos)) if sos else None
        self.fir = StatefulFIR(fir_taps) if fir_taps is not None else None
        self.gain = gain

    def __call__(self, v: np.ndarray) -> np.ndarray:
        y = self.gain * np.asarray(v, dtype=np.float64)
        if self.iir is not None:
            y = self.iir(y)
        if self.fir is not None:
            y = self.fir(y)
        return y

    def reset(self) -> None:
        if self.iir is not None:
            self.iir.reset()
        if self.fir is not None:
            self.fir.reset()
