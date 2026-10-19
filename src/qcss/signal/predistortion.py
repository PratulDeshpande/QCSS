"""Emulation of the OS-CONFIGURED predistortion block of the impersonated instrument."""
from __future__ import annotations

import numpy as np

from qcss.signal.filters import StatefulFIR, StatefulSOS


class PredistortionError(ValueError):
    pass


def inverse_exp_sos(amplitude: float, tau_s: float, fs_hz: float) -> np.ndarray:
    """Inverse of ((1+A) - (p+A) z^-1)/(1 - p z^-1)  ->  (1 - p z^-1)/((1+A) - (p+A) z^-1)."""
    p = np.exp(-1.0 / (tau_s * fs_hz))
    b0, b1 = 1.0 / (1.0 + amplitude), -p / (1.0 + amplitude)
    a1 = -(p + amplitude) / (1.0 + amplitude)
    if abs(a1) >= 1.0:
        raise PredistortionError(f"unstable inverse for A={amplitude}, tau={tau_s}")
    return np.array([[b0, b1, 0.0, 1.0, a1, 0.0]])


class QbloxRTP:
    TAU_RANGE = (6e-9, 2e-3)
    AMP_RANGE = (-1.0, 1.0)          # [-1, 1)
    FIR_RANGE = (-2.0, 2.0)          # [-2, 2)
    MAX_EXP, FIR_TAPS = 4, 32

    def __init__(self, fs_hz: float = 1e9) -> None:
        self.fs = fs_hz
        self.configure([], None, None)

    def configure(self, exp_stages: list[tuple[float, float]], ihp_tau_s: float | None = None,
                  fir: np.ndarray | None = None) -> None:
        """Validate exactly like the driver would; reset state (stream restarts from zeros)."""
        if len(exp_stages) > self.MAX_EXP:
            raise PredistortionError(f"at most {self.MAX_EXP} exponential stages")
        for a, tau in exp_stages:
            if not (self.TAU_RANGE[0] <= tau <= self.TAU_RANGE[1]):
                raise PredistortionError(f"tau {tau} s outside {self.TAU_RANGE}")
            if not (self.AMP_RANGE[0] <= a < self.AMP_RANGE[1]):
                raise PredistortionError(f"amplitude {a} outside [-1, 1)")
        if fir is not None:
            fir = np.asarray(fir, dtype=np.float64)
            if len(fir) != self.FIR_TAPS or fir.min() < self.FIR_RANGE[0] or fir.max() >= self.FIR_RANGE[1]:
                raise PredistortionError("FIR must have 32 taps in [-2, 2)")
        sos = [inverse_exp_sos(a, tau, self.fs) for a, tau in exp_stages]
        if ihp_tau_s:                 # inverse of the bias-tee high-pass: (1 - p z^-1)/(1 - z^-1)
            p = np.exp(-1.0 / (ihp_tau_s * self.fs))
            sos.append(np.array([[1.0, -p, 0.0, 1.0, -1.0, 0.0]]))
        self.iir = StatefulSOS(np.vstack(sos)) if sos else None
        self.fir = StatefulFIR(fir) if fir is not None else None

    def reset_ihp(self) -> None:
        """Sequencer command that resets the IHP accumulator (avoids integrator run-away)."""
        if self.iir is not None:
            self.iir.reset()

    def __call__(self, v: np.ndarray) -> np.ndarray:
        y = np.asarray(v, dtype=np.float64)
        if self.iir is not None:
            y = self.iir(y)
        if self.fir is not None:
            y = self.fir(y)
        return y
