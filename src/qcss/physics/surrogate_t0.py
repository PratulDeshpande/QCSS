"""Tier T0: fast surrogate engine for OS scheduler / telemetry tests.

Each qubit is a classical bit. A lifted pulse redistributes the bit by its actual unitary's
transition probabilities |U[:, b]|^2 (a pi pulse flips, a pi/2 pulse randomises, an idle
leaves it), and decay between operations relaxes 1 -> 0 at the device T1. Every draw uses
the shot's seeded generator.
"""
from __future__ import annotations

import numpy as np

from qcss.physics.lifter import GateEvent


class SurrogateT0:
    tier = "T0"
    noise_fidelity = "surrogate"
    pulse_level = False

    def __init__(self, n: int, t1_ns: list[float] | None = None) -> None:
        self.n = n
        self.t1 = np.full(n, np.inf) if t1_ns is None else np.asarray(t1_ns, dtype=float)
        self.state = np.zeros(n, dtype=int)   # classical bit string
        self.clock = np.zeros(n)

    def set_parameters(self, f01_ghz: list[float] | None = None, t1_ns: list[float] | None = None) -> None:
        if t1_ns is not None:
            self.t1 = np.asarray(t1_ns, dtype=float)

    def reset_state(self) -> None:
        self.state[:] = 0
        self.clock[:] = 0.0

    def _decay(self, q: int, t_ns: float, rng: np.random.Generator) -> None:
        dt = t_ns - self.clock[q]
        if dt > 0:
            if self.state[q] and rng.random() < -np.expm1(-dt / self.t1[q]):
                self.state[q] = 0
            self.clock[q] = t_ns

    def advance_to(self, t_ns: float, rng: np.random.Generator | None = None) -> None:
        if rng is None:
            raise ValueError("advance_to needs the shot's random generator")
        for q in range(self.n):
            self._decay(q, t_ns, rng)

    def apply_event(self, ev: GateEvent, rng: np.random.Generator) -> None:
        for q in ev.qubits:
            self._decay(q, ev.t_start, rng)
        b = 0
        for q in ev.qubits:
            b = (b << 1) | int(self.state[q])
        col = np.abs(ev.unitary[:, b]) ** 2
        out = int(rng.choice(len(col), p=col / col.sum()))
        for i, q in enumerate(reversed(ev.qubits)):
            self.state[q] = (out >> i) & 1
        for q in ev.qubits:
            self.clock[q] = max(self.clock[q], ev.t_end)

    def measure(self, q: int, t_now: float | None = None, rng: np.random.Generator | None = None) -> int:
        if rng is None:
            raise ValueError("measure needs the shot's random generator")
        if t_now is not None:
            self._decay(q, t_now, rng)
        return int(self.state[q])

    def level_probabilities(self, q: int) -> np.ndarray:
        p1 = float(self.state[q])
        return np.array([1.0 - p1, p1, 0.0])
