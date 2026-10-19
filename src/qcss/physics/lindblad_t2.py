"""Tier T2: multi-qutrit Lindblad engine, segment-based, absolute time in ns (QuTiP 5).

Frames and conventions:
  * Each qubit q is simulated in a rotating frame at f_frame[q] (its idle transition
    frequency unless set otherwise). Detuning Delta_q = 2 pi (f01_q - f_frame[q]) is in H at
    ALL times -- idle included -- so Ramsey fringes exist (fixes PH-01).
  * Drive: H_d = 1/2 (Omega_q(t) a_q^dag + Omega_q(t)^* a_q), Omega in rad/ns, produced by the
    port renderer on the generator's sample grid (frame phase, mixer, line already applied).
  * Exchange coupling J_qp (a_q^dag a_p e^{i(w_q - w_p) t} + h.c.) with w = frame freqs;
    ZZ, CZ/iSWAP resonances emerge from it.
  * Collapse ops: sqrt(g(1+nbar)) a, sqrt(g nbar) a^dag, sqrt(2 g_phi) n, with g the BARE rate
    derived from the measured T1 (PH-12). T2 means T2* (Ramsey).
  * Pulses that overlap in time are evolved TOGETHER in one segment (fixes PH-18).
  * Virtual Z never touches the state: it is a frame change and arrives as the phase of the
    drive samples.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import qutip as qt
from scipy.sparse.linalg import expm_multiply

from qcss.physics.populations import relax_populations
from qcss.physics.transmon import TWO_PI, bare_decay_rate, thermal_populations

DIM = 3


@dataclass
class QutritParams:
    f01_ghz: list[float]                 # idle transition frequencies
    alpha_ghz: list[float]               # anharmonicities (negative)
    t1_ns: list[float]                   # MEASURED T1
    t2_ns: list[float]                   # T2* (Ramsey); clipped to <= 2 T1
    nbar: list[float]                    # Bose occupation (NOT the excited population)
    frame_ghz: list[float]               # rotating-frame frequency per qubit
    couplings_ghz: dict[tuple[int, int], float] = field(default_factory=dict)   # J_qp
    extra_12_dephasing_per_ns: list[float] | None = None    # optional |2> dephasing (Peterer)


class LindbladT2:
    tier: str = "T2"
    noise_fidelity: str = "physical"
    pulse_level: bool = True

    def __init__(self, p: QutritParams) -> None:
        self.n = len(p.f01_ghz)
        self.a = [self._embed(qt.destroy(DIM), q) for q in range(self.n)]
        self.num = [x.dag() * x for x in self.a]
        self._setup(p)
        self.rho = self.thermal_state()
        self.clock = 0.0

    def _setup(self, p: QutritParams) -> None:
        self.p = p
        self.c_ops = self._collapse_ops()
        self.w_frame = [TWO_PI * f for f in p.frame_ghz]                    # rad/ns
        self._idle_cache: dict[int, qt.Qobj] = {}
        self._L_common: qt.Qobj | None = None

    def set_parameters(self, f01_ghz: list[float] | None = None, t1_ns: list[float] | None = None) -> None:
        """Device drift: new idle frequencies / T1 (frames stay where the OS put them)."""
        new = replace(self.p, f01_ghz=list(f01_ghz) if f01_ghz is not None else self.p.f01_ghz,
                      t1_ns=list(t1_ns) if t1_ns is not None else self.p.t1_ns)
        if new != self.p:
            self._setup(new)

    def reset_state(self) -> None:
        self.rho = self.thermal_state()
        self.clock = 0.0

    # ---------------------------------------------------------------------------------
    def _embed(self, op: qt.Qobj, q: int) -> qt.Qobj:
        ops = [qt.qeye(DIM)] * self.n
        ops[q] = op
        return qt.tensor(ops)

    def _collapse_ops(self) -> list[qt.Qobj]:
        c = []
        for q in range(self.n):
            nb = self.p.nbar[q]
            g = bare_decay_rate(self.p.t1_ns[q], nb)
            c.append(np.sqrt(g * (1 + nb)) * self.a[q])
            if nb > 0:
                c.append(np.sqrt(g * nb) * self.a[q].dag())
            t2 = min(self.p.t2_ns[q], 2 * self.p.t1_ns[q])
            g_phi = max(0.0, 1 / t2 - 1 / (2 * self.p.t1_ns[q]))
            if g_phi > 0:
                c.append(np.sqrt(2 * g_phi) * self.num[q])
            if self.p.extra_12_dephasing_per_ns and self.p.extra_12_dephasing_per_ns[q] > 0:
                p2 = self._embed(qt.basis(DIM, 2).proj(), q)
                c.append(np.sqrt(self.p.extra_12_dephasing_per_ns[q]) * p2)
        return c

    def thermal_state(self) -> qt.Qobj:
        return qt.tensor([qt.Qobj(np.diag(thermal_populations(nb, DIM))) for nb in self.p.nbar])

    def _h_static_in_frame(self, extra_detuning: dict[int, float] | None = None) -> qt.Qobj:
        h = 0 * self.num[0]
        for q in range(self.n):
            delta = TWO_PI * (self.p.f01_ghz[q] - self.p.frame_ghz[q]) + (extra_detuning or {}).get(q, 0.0)
            alpha = TWO_PI * self.p.alpha_ghz[q]
            h += delta * self.num[q] + 0.5 * alpha * self.a[q].dag() * self.a[q].dag() * self.a[q] * self.a[q]
        return h

    def _coupling_terms(self) -> list:
        terms = []
        for (q, r), j_ghz in self.p.couplings_ghz.items():
            j = TWO_PI * j_ghz
            dw = self.w_frame[q] - self.w_frame[r]
            op = self.a[q].dag() * self.a[r]
            if abs(dw) < 1e-15:
                terms.append(j * (op + op.dag()))
            else:   # time-dependent in the per-qubit frames; ABSOLUTE time t (ns)
                terms.append([op, lambda t, j=j, dw=dw: j * np.exp(1j * dw * t)])
                terms.append([op.dag(), lambda t, j=j, dw=dw: j * np.exp(-1j * dw * t)])
        return terms

    # ---------------------------------------------------------------------------------
    def evolve_segment(self, t0_ns: float, dt_ns: float,
                       drives: dict[int, np.ndarray] | None = None,
                       flux_detuning: dict[int, np.ndarray] | None = None) -> None:
        """Evolve self.rho over len(samples)*dt starting at ABSOLUTE time t0 (ns)."""
        arrays = list((drives or {}).values()) + list((flux_detuning or {}).values())
        if not arrays:
            return
        if t0_ns > self.clock:
            self.evolve_idle(self.clock, t0_ns - self.clock)
        n_samp = len(arrays[0])
        tlist = t0_ns + dt_ns * np.arange(n_samp + 1)              # sample starts + end
        pad = lambda x: np.append(x, x[-1])                           # hold last value
        h = [self._h_static_in_frame()] + self._coupling_terms()
        for q, om in (drives or {}).items():
            h.append([0.5 * self.a[q].dag(), pad(np.asarray(om, dtype=np.complex128))])
            h.append([0.5 * self.a[q], pad(np.conj(np.asarray(om, dtype=np.complex128)))])
        for q, d in (flux_detuning or {}).items():
            h.append([self.num[q], pad(np.asarray(d, dtype=np.float64))])
        H = qt.QobjEvo(h, tlist=tlist, order=0)                     # ZOH, exactly like a DAC
        opts = {"store_states": False, "store_final_state": True, "max_step": 0.5 * dt_ns,
                "nsteps": 1_000_000, "atol": 1e-10, "rtol": 1e-8}
        res = qt.mesolve(H, self.rho, [tlist[0], tlist[-1]], c_ops=self.c_ops, options=opts)
        self.rho = res.final_state
        self.clock = float(tlist[-1])

    # ---------------------------------------------------------------------------------
    def _frame_rotation(self, t_ns: float) -> qt.Qobj:
        """V(t) = exp(i sum_q (w_frame_q - w_ref) n_q t): common frame -> per-qubit frames."""
        w_ref = self.w_frame[0]
        gen = sum(((self.w_frame[q] - w_ref) * self.num[q] for q in range(self.n)), 0 * self.num[0])
        return (1j * gen * t_ns).expm()

    def _common_liouvillian(self) -> qt.Qobj:
        if self._L_common is None:
            w_ref = self.w_frame[0]
            h = 0 * self.num[0]
            for q in range(self.n):
                h += (TWO_PI * self.p.f01_ghz[q] - w_ref) * self.num[q]
                h += 0.5 * TWO_PI * self.p.alpha_ghz[q] * self.a[q].dag() ** 2 * self.a[q] ** 2
            for (q, r), j_ghz in self.p.couplings_ghz.items():
                op = self.a[q].dag() * self.a[r]
                h += TWO_PI * j_ghz * (op + op.dag())
            self._L_common = qt.liouvillian(h, self.c_ops)
        return self._L_common

    def evolve_idle(self, t0_ns: float, duration_ns: float) -> None:
        """Exact idle evolution via a STATIC Liouvillian in a common frame (no stiff ODE)."""
        if duration_ns <= 0:
            return
        self.clock = t0_ns + duration_ns
        if duration_ns >= 10 * max(min(t2, 2 * t1) for t1, t2 in zip(self.p.t1_ns, self.p.t2_ns, strict=True)):
            gam = [bare_decay_rate(t1, nb) for t1, nb in zip(self.p.t1_ns, self.p.nbar, strict=True)]
            pops = relax_populations(np.real(self.rho.diag()), gam, self.p.nbar, duration_ns)
            self.rho = qt.Qobj(np.diag(pops), dims=self.rho.dims)
            return
        v0 = self._frame_rotation(t0_ns)
        rho_c = v0.dag() * self.rho * v0
        L = self._common_liouvillian()
        dur = round(float(duration_ns * 1000))                      # cache key in ps
        if self.n <= 2:
            if dur not in self._idle_cache:
                self._idle_cache[dur] = (L * duration_ns).expm()
            rho_c = qt.vector_to_operator(self._idle_cache[dur] * qt.operator_to_vector(rho_c))
        else:
            vec = qt.operator_to_vector(rho_c).full().ravel()
            mat = L.data.as_scipy() if hasattr(L.data, "as_scipy") else L.data
            out = expm_multiply(mat * duration_ns, vec)
            rho_c = qt.vector_to_operator(qt.Qobj(out.reshape(-1, 1), dims=qt.operator_to_vector(rho_c).dims))
        v1 = self._frame_rotation(t0_ns + duration_ns)
        self.rho = v1 * rho_c * v1.dag()

    # ---------------------------------------------------------------------------------
    def advance_to(self, t_ns: float, rng: np.random.Generator | None = None) -> None:
        """Idle evolution from the engine clock to absolute time t_ns."""
        if t_ns > self.clock:
            self.evolve_idle(self.clock, t_ns - self.clock)

    def level_probabilities(self, q: int) -> np.ndarray:
        return np.real(self.rho.ptrace(q).diag()) if self.n > 1 else np.real(self.rho.diag())

    def joint_probabilities(self, qubits: list[int]) -> np.ndarray:
        """P(levels) over `qubits` (first qubit most significant), shape (3**k,)."""
        r = self.rho.ptrace(qubits) if self.n > 1 else self.rho
        if len(qubits) > 1 and list(qubits) != sorted(qubits):
            order = np.argsort(np.argsort(qubits))
            r = r.permute(list(order))
        p = np.clip(np.real(r.diag()), 0.0, None)
        return p / p.sum()

    def dephase_measured(self, qubits: list[int]) -> None:
        """Non-selective projective measurement (ensemble mode): rho -> sum_k P_k rho P_k."""
        for q in qubits:
            projs = [self._embed(qt.basis(DIM, k).proj(), q) for k in range(DIM)]
            self.rho = sum((P * self.rho * P for P in projs), 0 * self.rho)

    def measure(self, q: int, t_now: float | None = None, rng: np.random.Generator | None = None) -> int:
        """Projective qutrit measurement with collapse (Born rule)."""
        if rng is None:
            raise ValueError("measure needs the shot's random generator")
        if t_now is not None:
            self.advance_to(t_now)
        p = np.clip(self.level_probabilities(q), 0, None)
        k = int(rng.choice(DIM, p=p / p.sum()))
        proj = self._embed(qt.basis(DIM, k).proj(), q)
        self.rho = proj * self.rho * proj
        tr = float(np.real(self.rho.tr()))
        if tr > 0:
            self.rho = self.rho / tr
        return k
