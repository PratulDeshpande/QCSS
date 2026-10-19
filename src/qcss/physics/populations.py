"""Exact population dynamics for long idle / inter-shot delays (no ODE).

With a diagonal idle Hamiltonian and local dissipators D[a], D[a^dag], D[n], the
diagonal of rho obeys a closed classical master equation. Per qutrit the 3x3 rate
matrix (columns sum to zero, sqrt(n) ladder => Gamma_21 = 2 Gamma_10, as measured by
Peterer et al. 2015) is exponentiated once and applied as a Kronecker product: O(9^n).
Coherences decay at least as e^{-t/T2}; for t >= 10*T2 they are set to zero.
(With exchange coupling J present this is an approximation for long delays only.)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.linalg import expm


def rate_matrix(gamma: float, nbar: float) -> np.ndarray:
    d, u = gamma * (1.0 + nbar), gamma * nbar
    return np.array([[-u,        d,           0.0],
                     [ u, -(d + 2 * u),   2 * d],
                     [0.0,     2 * u,    -2 * d]], dtype=np.float64)


@lru_cache(maxsize=256)
def _transfer(gamma: float, nbar: float, t_ns: float) -> np.ndarray:
    return expm(rate_matrix(gamma, nbar) * t_ns)


def relax_populations(p: np.ndarray, gammas: list[float], nbars: list[float], t_ns: float) -> np.ndarray:
    """p: joint populations, shape (3,)*n (qubit 0 = most significant axis)."""
    n = len(gammas)
    p = np.asarray(p, dtype=np.float64).reshape((3,) * n)
    for q in range(n):
        tq = _transfer(float(gammas[q]), float(nbars[q]), float(t_ns))
        p = np.moveaxis(np.tensordot(tq, p, axes=([1], [q])), 0, q)
    return p.reshape(-1)
