"""Pulse -> gate lifting from physics (plan Phase 7, steps a-d).

A gate-level tier never guesses what a pulse is from its waveform name. The executor renders
every play into its actual drive samples (frame phase, mixer and line effects included);
the lifter integrates those samples on a closed qutrit (or a few coupled qutrits) and returns
the computational-subspace unitary plus leakage. Clifford identification for the stabilizer
tier compares the nearest unitary to the complete 1- and 2-qubit Clifford groups.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import stim
from scipy.linalg import expm, sqrtm

CLIFFORD_RZ_TOL = 1e-9
CLIFFORD_FIDELITY_MIN = 0.99          # process fidelity of the unitary part to its nearest Clifford

_PAULI_1Q = [
    np.eye(2, dtype=complex),
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.diag([1.0, -1.0]).astype(complex),
]


@dataclass
class GateEvent:
    """One lifted operation: what the pulse actually did to the qubits it touched."""
    qubits: tuple[int, ...]
    unitary: np.ndarray                    # 2^k x 2^k, big-endian over `qubits` (not necessarily unitary)
    t_start: float                         # ns
    t_end: float                           # ns
    leakage: float = 0.0
    name: str = ""
    clifford: np.ndarray | None = None     # nearest Clifford when within CLIFFORD_FIDELITY_MIN
    clifford_fidelity: float = 0.0
    rz_angles: list[float] = field(default_factory=list)
    driven: tuple[int, ...] | None = None  # qubits the pulse acts on directly (default: all of `qubits`)

    @property
    def is_clifford(self) -> bool:
        return self.clifford is not None


def is_clifford_rz(theta: float) -> bool:
    k = theta / (np.pi / 2.0)
    return abs(k - round(k)) < CLIFFORD_RZ_TOL


# ----------------------------------------------------------------------------- integration
def _qutrit_ops(alpha_rad_ns: float):
    a = np.diag([1.0, np.sqrt(2.0)], k=1).astype(complex)
    n = a.conj().T @ a
    h_anh = 0.5 * alpha_rad_ns * (a.conj().T @ a.conj().T @ a @ a)
    return a, n, h_anh


def lift_1q(omega: np.ndarray, dt_ns: float, alpha_rad_ns: float, detuning_rad_ns: float = 0.0) -> tuple[np.ndarray, float]:
    """Return (U_2x2, leakage) for complex drive samples omega (rad/ns), ZOH steps."""
    omega = np.ascontiguousarray(omega, dtype=np.complex128)
    key = hashlib.blake2b(omega.tobytes() + np.array([dt_ns, alpha_rad_ns, detuning_rad_ns]).tobytes(),
                          digest_size=16).digest()
    u2, leak = _lift_cached(key, omega.tobytes(), float(dt_ns), float(alpha_rad_ns), float(detuning_rad_ns))
    return u2.copy(), leak


@lru_cache(maxsize=4096)
def _lift_cached(_key: bytes, omega_bytes: bytes, dt_ns: float, alpha: float, det: float) -> tuple[np.ndarray, float]:
    omega = np.frombuffer(omega_bytes, dtype=np.complex128)
    a, n, h_anh = _qutrit_ops(alpha)
    u = np.eye(3, dtype=complex)
    for w in omega:
        h = det * n + h_anh + 0.5 * (w * a.conj().T + np.conj(w) * a)
        u = expm(-1j * h * dt_ns) @ u
    u2 = u[:2, :2]
    leakage = float(1.0 - np.mean(np.sum(np.abs(u2) ** 2, axis=0)))
    return u2, leakage


def _embed(op: np.ndarray, q: int, n: int, dim: int = 3) -> np.ndarray:
    out = np.array([[1.0 + 0j]])
    for k in range(n):
        out = np.kron(out, op if k == q else np.eye(dim))
    return out


def lift_multi(n_qubits: int, dt_ns: float, n_samples: int, detunings_rad_ns: list[float],
               alphas_rad_ns: list[float], couplings_rad_ns: dict[tuple[int, int], float] | None = None,
               drives: dict[int, np.ndarray] | None = None, flux: dict[int, np.ndarray] | None = None,
               frame_rad_ns: list[float] | None = None, t0_ns: float = 0.0) -> tuple[np.ndarray, float]:
    """Closed-system propagator of k coupled qutrits over n ZOH samples -> (U on 2^k, leakage).

    Same Hamiltonian as Tier T2 without dissipation: detuning + anharmonicity per qutrit,
    drive 1/2 (Omega a^dag + h.c.), flux detuning on n, exchange J (a_q^dag a_p e^{i(w_q-w_p)t} + h.c.)
    in absolute time.
    """
    couplings_rad_ns = couplings_rad_ns or {}
    drives, flux = drives or {}, flux or {}
    frame = frame_rad_ns or [0.0] * n_qubits
    a1, n1, _ = _qutrit_ops(0.0)
    a = [_embed(a1, q, n_qubits) for q in range(n_qubits)]
    num = [_embed(n1, q, n_qubits) for q in range(n_qubits)]
    h0 = sum((detunings_rad_ns[q] * num[q]
              + 0.5 * alphas_rad_ns[q] * a[q].conj().T @ a[q].conj().T @ a[q] @ a[q]) for q in range(n_qubits))
    h0 = np.asarray(h0, dtype=complex)
    dim = 3 ** n_qubits
    u = np.eye(dim, dtype=complex)
    for k in range(n_samples):
        t = t0_ns + (k + 0.5) * dt_ns
        h = h0.copy()
        for (q, p), j in couplings_rad_ns.items():
            op = a[q].conj().T @ a[p]
            ph = np.exp(1j * (frame[q] - frame[p]) * t)
            h += j * (ph * op + np.conj(ph) * op.conj().T)
        for q, w in drives.items():
            h += 0.5 * (w[k] * a[q].conj().T + np.conj(w[k]) * a[q])
        for q, d in flux.items():
            h += d[k] * num[q]
        u = expm(-1j * h * dt_ns) @ u
    comp = [i for i in range(dim) if all(int(d) < 2 for d in np.base_repr(i, 3).rjust(n_qubits, "0"))]
    uc = u[np.ix_(comp, comp)]
    leakage = float(1.0 - np.mean(np.sum(np.abs(uc) ** 2, axis=0)))
    return uc, leakage


def shift_lift_start(u: np.ndarray, frame_rad_ns: list[float], tau_ns: float) -> np.ndarray:
    """A drive-free lift_multi result moved from start t0 to t0 + tau, exactly.

    Without drives, time enters H(t) only through the exchange phases e^{i(w_q - w_p) t}, so
    H(t + tau) = R^dag H(t) R with R = exp(-i tau sum_q w_q n_q), hence U(t0 + tau) = R^dag U(t0) R.
    R is diagonal, and so is its restriction to the computational states (big-endian bits).
    """
    if tau_ns == 0.0:
        return u
    n = len(frame_rad_ns)
    bits = (np.arange(2 ** n)[:, None] >> np.arange(n - 1, -1, -1)) & 1
    phase = np.exp(1j * tau_ns * (bits @ np.asarray(frame_rad_ns, dtype=float)))
    return phase[:, None] * u * np.conj(phase)[None, :]


# ----------------------------------------------------------------------------- Cliffords
@lru_cache(maxsize=2)
def _clifford_group(n: int) -> np.ndarray:
    """All n-qubit Cliffords (n = 1: 24, n = 2: 11520) as big-endian unitaries, up to global phase."""
    raw = np.array([t.to_unitary_matrix(endian="big") for t in stim.Tableau.iter_all(n)], dtype=np.complex128)
    # stim returns complex64; Clifford entries are exactly {0, 1/2, 1/sqrt2, 1} x e^{i k pi/4}: snap them
    mags = np.array([0.0, 0.5, np.sqrt(0.5), 1.0])
    mag = mags[np.argmin(np.abs(np.abs(raw)[..., None] - mags), axis=-1)]
    phase = np.round(np.angle(raw) / (np.pi / 4)) * (np.pi / 4)
    return mag * np.exp(1j * phase)


def nearest_unitary(m: np.ndarray) -> np.ndarray:
    """Polar decomposition: the unitary closest to m (leakage removed, rotation kept)."""
    h = sqrtm(m.conj().T @ m)
    return m @ np.linalg.inv(h) if np.linalg.cond(h) < 1e12 else m


def nearest_clifford(u: np.ndarray) -> tuple[np.ndarray, float]:
    """(nearest Clifford C, process fidelity |Tr(C^dag W)|^2 / d^2) for the unitary part W of u."""
    d = u.shape[0]
    n = round(np.log2(d))
    if 2 ** n != d or n > 2:
        raise ValueError("nearest_clifford supports 1 or 2 qubits")
    w = nearest_unitary(np.asarray(u, dtype=complex))
    group = _clifford_group(n)
    fid = np.abs(np.einsum("kij,ij->k", group.conj(), w)) ** 2 / d ** 2
    k = int(np.argmax(fid))
    return group[k], float(fid[k])


def is_clifford_unitary(u: np.ndarray, min_fidelity: float = CLIFFORD_FIDELITY_MIN) -> bool:
    if u.shape[0] > 4:
        return False
    return nearest_clifford(u)[1] >= min_fidelity


def pauli_twirl(err: np.ndarray) -> np.ndarray:
    """Pauli-twirl an error unitary E (1 or 2 qubits): p_P = |Tr(P^dag E)|^2 / d^2, P in {I,X,Y,Z}^n."""
    d = err.shape[0]
    paulis = _PAULI_1Q if d == 2 else [np.kron(a, b) for a in _PAULI_1Q for b in _PAULI_1Q]
    p = np.array([abs(np.trace(P.conj().T @ err)) ** 2 / d ** 2 for P in paulis])
    return p / p.sum()


def annotate_clifford(ev: GateEvent, min_fidelity: float = CLIFFORD_FIDELITY_MIN) -> GateEvent:
    if len(ev.qubits) <= 2:
        c, fid = nearest_clifford(ev.unitary)
        ev.clifford_fidelity = fid
        ev.clifford = c if fid >= min_fidelity else None
    return ev
