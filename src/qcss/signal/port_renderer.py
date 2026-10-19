"""Port rendering: programmed samples -> the drive the qubit actually sees (fault seam 1).

Drive ports (plan Phase 5, order of the port renderer):
    m_IF[n] = A env[n] e^{i(phi_frame + phi_offset)} e^{i 2 pi f_IF t_n}     NCO-modulated DAC stream
    m       = OS IQ correction (offsets, gain ratio, phase)                  what the OS programs
    x       = mu m + nu m* + d                                               hidden mixer truth + LO leakage
    Omega   = rabi * x * e^{i 2 pi (f_LO - f_frame) t_n}                     qubit rotating frame
With an ideal mixer Omega = rabi * A env e^{i phi}; the image lands at -2 f_IF and the LO at
-f_IF in the qubit frame, both off resonance, as on hardware (SC-09).

Flux ports keep ONE continuous stream per port: the OS predistortion and the hidden line
response are stateful filters whose tails carry from pulse to pulse and shot to shot (SC-06).
"""
from __future__ import annotations

import numpy as np

from qcss.signal.filters import FluxLineModel
from qcss.signal.mixer import IQCorrection, IQImpairment, apply_mixer
from qcss.signal.predistortion import QbloxRTP


class DriveChain:
    def __init__(self, fs_hz: float, f_lo_hz: float | None, f_phys_frame_hz: float, rabi_rad_ns: float,
                 truth: IQImpairment | None = None, correction: IQCorrection | None = None) -> None:
        self.fs = fs_hz
        self.f_lo = f_lo_hz or 0.0                 # rf_direct ports synthesise the carrier: LO = 0
        self.f_phys = f_phys_frame_hz
        self.rabi = rabi_rad_ns
        self.truth = truth or IQImpairment()
        self.correction = correction or IQCorrection()

    @property
    def ideal(self) -> bool:
        return self.truth == IQImpairment() and self.correction == IQCorrection()

    def render(self, env_phased: np.ndarray, t_ns: np.ndarray, f_if_hz: float) -> np.ndarray:
        """env_phased = A env e^{i phi} at the DAC samples; t_ns = absolute sample times. -> Omega (rad/ns)."""
        env_phased = np.asarray(env_phased, dtype=np.complex128)
        t_s = np.asarray(t_ns, dtype=np.float64) * 1e-9
        if self.ideal:
            # exact cancellation of NCO and down-conversion when f_LO + f_IF = f_frame
            return self.rabi * env_phased * np.exp(2j * np.pi * (self.f_lo + f_if_hz - self.f_phys) * t_s)
        m_if = env_phased * np.exp(2j * np.pi * f_if_hz * t_s)
        x = apply_mixer(m_if, self.truth, self.correction, lo_enabled=True)
        return self.rabi * x * np.exp(2j * np.pi * (self.f_lo - self.f_phys) * t_s)


class FluxChain:
    """OS-configured predistortion followed by the physical line, both continuous per port."""

    def __init__(self, truth: FluxLineModel | None = None, predistortion: QbloxRTP | None = None) -> None:
        self.truth = truth
        self.pre = predistortion
        self.next_sample = 0                      # first sample index not yet streamed

    @staticmethod
    def _idle(f, n: int) -> None:
        if f is None or n <= 0:
            return
        if getattr(f, "iir", None) is not None:
            f.iir.fast_forward_zeros(n)
        if getattr(f, "fir", None) is not None:
            f.fir(np.zeros(min(n, len(f.fir.b))))

    def reset(self) -> None:
        for f in (self.truth, self.pre):
            if f is not None:
                (f.reset_ihp if isinstance(f, QbloxRTP) else f.reset)()
        self.next_sample = 0

    def render(self, v: np.ndarray, start_sample: int) -> np.ndarray:
        gap = start_sample - self.next_sample
        if gap < 0:
            raise ValueError(f"flux play at sample {start_sample} overlaps the stream (next {self.next_sample})")
        self._idle(self.pre, gap)
        self._idle(self.truth, gap)
        y = np.asarray(v, dtype=np.float64)
        if self.pre is not None:
            y = self.pre(y)
        if self.truth is not None:
            y = self.truth(y)
        self.next_sample = start_sample + len(v)
        return y
