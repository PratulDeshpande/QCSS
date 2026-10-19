"""Pauli-twirl approximations -- for T1a (Stim) ONLY.

Idle PTA of amplitude + phase damping (Ghosh, Fowler, Geller, PRA 86, 062318 (2012), Eq. 10):
    p_X = p_Y = (1 - e^{-t/T1}) / 4
    p_Z       = (1 - e^{-t/T2}) / 2 - (1 - e^{-t/T1}) / 4
"""
from __future__ import annotations

import numpy as np


def idle_pta(t_ns: float, t1_ns: float, t2_ns: float) -> tuple[float, float, float]:
    if t_ns <= 0:
        return 0.0, 0.0, 0.0
    t2 = min(t2_ns, 2.0 * t1_ns)
    pxy = 0.25 * -np.expm1(-t_ns / t1_ns)
    pz = 0.5 * -np.expm1(-t_ns / t2) - pxy
    return float(pxy), float(pxy), float(max(pz, 0.0))


def twirl_unitary_error(err_2x2: np.ndarray) -> np.ndarray:
    """Pauli-twirl a single-qubit error unitary E = U_actual G_ideal^dag:
    p_P = |Tr(P^dag E)|^2 / d^2 for P in (I, X, Y, Z)."""
    paulis = [
        np.eye(2, dtype=complex),
        np.array([[0, 1], [1, 0]], dtype=complex),
        np.array([[0, -1j], [1j, 0]], dtype=complex),
        np.diag([1.0, -1.0]).astype(complex),
    ]
    return np.array([abs(np.trace(P.conj().T @ err_2x2)) ** 2 / 4.0 for P in paulis], dtype=np.float64)
