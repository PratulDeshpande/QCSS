"""Unit tests for exact population relaxation rate matrix."""
from __future__ import annotations

import numpy as np

from qcss.physics.populations import rate_matrix, relax_populations
from qcss.physics.transmon import thermal_populations


def test_rate_matrix_columns_sum_to_zero():
    gamma = 1.0 / 50_000.0  # 1 / 50 us
    nbar = 0.02
    R = rate_matrix(gamma, nbar)
    # Sum of each column must be 0 (conserves probability d(sum P)/dt = sum_i R_ij = 0)
    col_sums = np.sum(R, axis=0)
    assert np.allclose(col_sums, 0.0, atol=1e-15)


def test_relax_populations_exponential_decay():
    gamma = 1.0 / 50_000.0  # T1 = 50 us
    nbar = 0.0
    # Start in |1>
    p0 = np.array([0.0, 1.0, 0.0])
    t_ns = 20_000.0  # 20 us

    p_t = relax_populations(p0, [gamma], [nbar], t_ns)
    # At T=0, P1(t) = e^{-t / T1} = e^{-20/50} = 0.670320046
    expected_p1 = np.exp(-t_ns * gamma)
    assert np.isclose(p_t[1], expected_p1, atol=1e-5)
    assert np.isclose(np.sum(p_t), 1.0)


def test_relax_populations_thermal_steady_state():
    gamma = 1.0 / 50_000.0
    nbar = 0.03
    # Start in |2>
    p0 = np.array([0.0, 0.0, 1.0])
    # Relax for 10 ms (200 T1s)
    t_long = 10_000_000.0

    p_inf = relax_populations(p0, [gamma], [nbar], t_long)
    expected = thermal_populations(nbar, dim=3)
    assert np.allclose(p_inf, expected, atol=1e-6)


def test_relax_populations_two_qubits():
    gammas = [1.0 / 40_000.0, 1.0 / 60_000.0]
    nbars = [0.01, 0.02]
    # Start in |11> (index 1*3 + 1 = 4)
    p0 = np.zeros(9)
    p0[4] = 1.0

    t_ns = 20_000.0
    p_t = relax_populations(p0, gammas, nbars, t_ns)
    assert np.isclose(np.sum(p_t), 1.0)
    # Qubit 0 should have decayed by e^{-20/40} = e^{-0.5}
    # Qubit 1 should have decayed by e^{-20/60} = e^{-1/3}
    p_q0_1 = p_t[3] + p_t[4] + p_t[5]
    assert np.isclose(p_q0_1, np.exp(-0.5), atol=0.02)
