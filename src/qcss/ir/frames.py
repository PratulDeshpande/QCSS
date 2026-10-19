"""Frames: phase/frequency references that channels bind to.

A virtual Z is a change of the QUBIT frame, so it must reach every channel whose
phase is referenced to that qubit -- including cross-resonance drives, which bind
to the TARGET qubit's frame (McKay et al. 2017). The NCO is a phase accumulator:
    phi(t) = phi0 + sum_k 2*pi*f_k * (t_{k+1} - t_k) + sum deltas
quantised to the impersonated instrument's phase and frequency resolution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

TWO_PI = 2.0 * math.pi


@dataclass
class FrameState:
    frame_id: str
    freq_hz: float                 # NCO / IF frequency of this frame
    phase_rad: float = 0.0         # accumulated explicit phase (virtual Z, set_phase)
    t_ref_tick: int = 0            # tick at which the accumulator was last re-referenced
    acc_rad: float = 0.0           # phase accumulated by frequency up to t_ref_tick
    pending: list = field(default_factory=list)   # latched ops waiting for the next RT instruction


class FrameTracker:
    def __init__(self, tick_hz: Fraction, frames: dict[str, float], *,
                 phase_steps: int = 10**9, freq_resolution_hz: float = 0.25,
                 phase_continuous_freq_switch: bool = True, latched: bool = True) -> None:
        self.tick_s = float(1 / tick_hz)
        self.phase_steps = phase_steps
        self.freq_res = freq_resolution_hz
        self.continuous = phase_continuous_freq_switch
        self.latched = latched
        self.frames = {fid: FrameState(fid, self._qf(f)) for fid, f in frames.items()}

    # -- quantisation -------------------------------------------------------------------
    def _qf(self, f_hz: float) -> float:
        return round(f_hz / self.freq_res) * self.freq_res if self.freq_res > 0 else f_hz

    def _qp(self, phi: float) -> float:
        step = TWO_PI / self.phase_steps
        return (round((phi % TWO_PI) / step) * step) % TWO_PI

    # -- operations (from the compiled program, in program order) -----------------------
    def shift_phase(self, fid: str, delta: float, tick: int) -> None:
        self._apply_or_latch(fid, ("shift", delta), tick)

    def set_phase(self, fid: str, phase: float, tick: int) -> None:
        self._apply_or_latch(fid, ("set", phase), tick)

    def reset_phase(self, fid: str, tick: int) -> None:
        self._apply_or_latch(fid, ("reset", 0.0), tick)

    def set_frequency(self, fid: str, f_hz: float, tick: int) -> None:
        self._apply_or_latch(fid, ("freq", f_hz), tick)

    def on_rt_instruction(self, fid: str, tick: int) -> None:
        """Latched parameters take effect at the next real-time instruction (Qblox semantics)."""
        fr = self.frames[fid]
        for op in fr.pending:
            self._apply(fr, op, tick)
        fr.pending.clear()

    def _apply_or_latch(self, fid: str, op: tuple, tick: int) -> None:
        fr = self.frames[fid]
        if self.latched:
            fr.pending.append(op)
        else:
            self._apply(fr, op, tick)

    def _apply(self, fr: FrameState, op: tuple, tick: int) -> None:
        kind, val = op
        if kind == "shift":
            fr.phase_rad = (fr.phase_rad + val) % TWO_PI
        elif kind == "set":
            fr.phase_rad = val % TWO_PI
        elif kind == "reset":                # t' -> 0, accumulator -> 0, phase -> 0
            fr.phase_rad, fr.acc_rad, fr.t_ref_tick = 0.0, 0.0, tick
        elif kind == "freq":
            # bank the phase accumulated at the old frequency, then switch
            fr.acc_rad = self.accumulated(fr.frame_id, tick) if self.continuous else 0.0
            fr.t_ref_tick = tick
            fr.freq_hz = self._qf(val)

    # -- queries -------------------------------------------------------------------------
    def accumulated(self, fid: str, tick: int) -> float:
        fr = self.frames[fid]
        return fr.acc_rad + TWO_PI * fr.freq_hz * (tick - fr.t_ref_tick) * self.tick_s

    def phase_at(self, fid: str, tick: int) -> float:
        """Absolute NCO phase (accumulator + explicit phase), quantised."""
        return self._qp(self.accumulated(fid, tick) + self.frames[fid].phase_rad)

    def explicit_phase(self, fid: str) -> float:
        return self._qp(self.frames[fid].phase_rad)
