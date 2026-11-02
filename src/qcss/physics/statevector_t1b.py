"""Tier T1b: statevector Monte-Carlo with EXACT amplitude-damping + dephasing trajectories.

Gates are the LIFTED actual unitaries of the rendered pulses (coherent errors keep their N^2
growth). Decoherence is charged per qubit for the time since that qubit was last updated,
including during its own gates (TR-03). Big-endian: qubit 0 is the most significant axis.
Leakage out of the qubit subspace is not represented at this tier (route to T2 for it).
"""
from __future__ import annotations

import numpy as np

from qcss.physics.lifter import GateEvent, nearest_unitary

THERMALISED_AFTER_T1 = 20.0      # idle longer than this many T1 and a warm qubit has forgotten its state (e^-20)


class StatevectorT1b:
    tier = "T1B"
    noise_fidelity = "physical"
    pulse_level = False

    def __init__(self, n: int, t1_ns: list[float], t2_ns: list[float], nbar: list[float] | None = None,
                 dtype=np.complex128, seed: int = 42) -> None:
        self.n = n
        self.dtype = dtype
        self.nbar = np.zeros(n) if nbar is None else np.asarray(nbar, dtype=float)
        self.p_eq = self.nbar / (1 + 2 * self.nbar)   # thermal excited population the qubits relax to
        self._t2_spec = np.asarray(t2_ns, dtype=float)
        self.set_parameters(t1_ns=t1_ns)
        self.psi = np.zeros(1 << n, dtype=dtype)
        self.clock = np.zeros(n)                      # last update time per qubit (ns)
        self._rng = np.random.default_rng(seed)
        self.reset_state()

    def set_parameters(self, f01_ghz: list[float] | None = None, t1_ns: list[float] | None = None) -> None:
        if t1_ns is not None:
            self.t1 = np.asarray(t1_ns, dtype=float)
            self.t2 = np.minimum(self._t2_spec, 2 * self.t1)

    # -- helpers ----------------------------------------------------------------------
    def _t(self) -> np.ndarray:
        t = self.psi.reshape((2,) * self.n)
        assert np.shares_memory(t, self.psi)          # in-place edits must hit the real buffer
        return t

    def _sl(self, q: int, v: int) -> tuple:
        s: list[slice | int] = [slice(None)] * self.n
        s[q] = v
        return tuple(s)

    def reset_state(self) -> None:
        """A thermal start: each qubit excited with its equilibrium probability (|0...0> when cold)."""
        self.psi[:] = 0.0
        hot = self._rng.random(self.n) < self.p_eq if self.p_eq.any() else np.zeros(self.n, dtype=bool)
        self.psi[int("".join("1" if b else "0" for b in hot), 2) if self.n else 0] = 1.0
        self.clock[:] = 0.0

    # -- noise ------------------------------------------------------------------------
    def _amp_damp(self, q: int, dt: float, rng: np.random.Generator) -> None:
        """Generalized amplitude damping as quantum jumps: down at (1 - p_eq) / T1, up at p_eq / T1.
        A warm qubit's interval is split into steps of at most T1 / 10 so both channels stay accurate."""
        p_eq = self.p_eq[q]
        if p_eq <= 0.0:
            self._jump_down(q, -np.expm1(-dt / self.t1[q]), rng)
            return
        if dt >= THERMALISED_AFTER_T1 * self.t1[q]:
            # Fully relaxed (memory left: e^-20): the exact limit of the channel is a fresh thermal qubit.
            # Without this a very short T1 (a killed qubit) makes the step count grow as dt / T1.
            self._jump_down(q, 1.0, rng)
            self._jump_up(q, p_eq, rng)
            return
        steps = max(1, int(np.ceil(10 * dt / self.t1[q])))          # at most 10 x THERMALISED_AFTER_T1
        h = dt / steps
        g_down, g_up = -np.expm1(-h * (1 - p_eq) / self.t1[q]), -np.expm1(-h * p_eq / self.t1[q])
        for _ in range(steps):
            self._jump_down(q, g_down, rng)
            self._jump_up(q, g_up, rng)

    def _jump_up(self, q: int, g: float, rng: np.random.Generator) -> None:
        t = self._t()
        i0, i1 = self._sl(q, 0), self._sl(q, 1)
        p0 = float(np.vdot(t[i0], t[i0]).real)
        if p0 <= 1e-15:
            return
        if rng.random() < g * p0:                     # thermal excitation |0> -> |1>
            t[i1] = t[i0] / np.sqrt(p0)
            t[i0] = 0.0
        else:
            t[i0] *= np.sqrt(max(0.0, 1.0 - g))
            norm = float(np.vdot(self.psi, self.psi).real)
            if norm > 0:
                self.psi /= np.sqrt(norm)

    def _jump_down(self, q: int, g: float, rng: np.random.Generator) -> None:
        t = self._t()
        i0, i1 = self._sl(q, 0), self._sl(q, 1)
        p1 = float(np.vdot(t[i1], t[i1]).real)
        if p1 <= 1e-15:
            return
        if rng.random() < g * p1:                     # quantum jump |1> -> |0>
            t[i0] = t[i1] / np.sqrt(p1)
            t[i1] = 0.0
        else:                                         # no-jump evolution, renormalised
            t[i1] *= np.sqrt(max(0.0, 1.0 - g))
            norm = float(np.vdot(self.psi, self.psi).real)
            if norm > 0:
                self.psi /= np.sqrt(norm)

    def _dephase(self, q: int, dt: float, rng: np.random.Generator) -> None:
        g_phi = max(0.0, 1.0 / self.t2[q] - 0.5 / self.t1[q])
        if rng.random() < 0.5 * -np.expm1(-dt * g_phi):
            self._t()[self._sl(q, 1)] *= -1.0

    def advance(self, q: int, t_now: float, rng: np.random.Generator | None = None) -> None:
        gen = rng if rng is not None else self._rng
        dt = t_now - self.clock[q]
        if dt > 0:
            self._amp_damp(q, dt, gen)
            self._dephase(q, dt, gen)
            self.clock[q] = t_now

    def advance_to(self, t_ns: float, rng: np.random.Generator | None = None) -> None:
        """Charge decoherence on every qubit up to absolute time t_ns."""
        for q in range(self.n):
            self.advance(q, t_ns, rng)

    def idle_until(self, t_now: float, rng: np.random.Generator | None = None) -> None:
        self.advance_to(t_now, rng)

    # -- operations -------------------------------------------------------------------
    def apply_unitary(self, u: np.ndarray, qubits: tuple[int, ...], t_start: float, t_end: float,
                      rng: np.random.Generator | None = None) -> None:
        """Charge decoherence for [last update, t_start), apply U, then for the gate duration."""
        gen = rng if rng is not None else self._rng
        for q in qubits:
            self.advance(q, t_start, gen)
        k = len(qubits)
        t = self.psi.reshape((2,) * self.n)
        ut = np.asarray(u, dtype=self.dtype).reshape((2,) * (2 * k))
        out_axes = list(range(self.n))
        g_out = [self.n + i for i in range(k)]
        for i, q in enumerate(qubits):
            out_axes[q] = g_out[i]
        res = np.einsum(ut, g_out + list(qubits), t, list(range(self.n)), out_axes)
        self.psi = np.ascontiguousarray(res).reshape(-1)
        for q in qubits:
            self.advance(q, t_end, gen)

    def apply_event(self, ev: GateEvent, rng: np.random.Generator) -> None:
        """Apply what a rendered pulse actually did (unitary part of its lifted propagator)."""
        self.apply_unitary(nearest_unitary(ev.unitary), ev.qubits, ev.t_start, ev.t_end, rng)

    def measure(self, q: int, t_now: float | None = None, rng: np.random.Generator | None = None) -> int:
        gen = rng if rng is not None else self._rng
        if t_now is not None:
            self.advance(q, t_now, gen)
        t = self._t()
        p1 = float(np.vdot(t[self._sl(q, 1)], t[self._sl(q, 1)]).real)
        m = int(gen.random() < p1)
        t[self._sl(q, 1 - m)] = 0.0
        norm = float(np.vdot(self.psi, self.psi).real)
        if norm > 0:
            self.psi /= np.sqrt(norm)
        return m

    def level_probabilities(self, q: int) -> np.ndarray:
        t = self._t()
        p1 = float(np.vdot(t[self._sl(q, 1)], t[self._sl(q, 1)]).real)
        return np.array([1.0 - p1, p1, 0.0])

    def reset(self, q: int, t_now: float, rng: np.random.Generator | None = None) -> None:
        gen = rng if rng is not None else self._rng
        if self.measure(q, t_now, gen):
            self.apply_unitary(np.array([[0, 1], [1, 0]], dtype=complex), (q,), t_now, t_now, gen)
