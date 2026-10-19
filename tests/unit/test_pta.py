"""Unit tests for Pauli-twirl approximation (PTA) and Ghosh formula."""
from __future__ import annotations

import numpy as np

from qcss.physics.pta import idle_pta, twirl_unitary_error


def test_ghosh_idle_pta_formula():
    t1_ns = 50_000.0   # 50 us
    t2_ns = 100_000.0  # 100 us
    t_ns = 1_000.0     # 1 us

    px, py, pz = idle_pta(t_ns, t1_ns, t2_ns)

    # p_x = p_y = (1 - exp(-1/50)) / 4 ~ 4.95e-3
    assert px == py
    assert np.isclose(px, 0.25 * (1.0 - np.exp(-1.0 / 50.0)), rtol=1e-5)

    # p_z = (1 - exp(-1/100)) / 2 - p_x ~ 2.48e-5
    # The draft omitted the -p_x term and got 4.95e-3 (a 200x error)
    assert np.isclose(pz, 2.475e-5, rtol=0.01)


def test_twirl_unitary_error_pauli_decomposition():
    # Small X over-rotation: R_x(eps) = exp(-i eps/2 X) = cos(eps/2) I - i sin(eps/2) X
    eps = 0.05
    u_err = np.array([
        [np.cos(eps / 2), -1j * np.sin(eps / 2)],
        [-1j * np.sin(eps / 2), np.cos(eps / 2)],
    ], dtype=complex)

    probs = twirl_unitary_error(u_err)
    # p_I, p_X, p_Y, p_Z
    p_i, p_x, p_y, p_z = probs
    assert np.isclose(np.sum(probs), 1.0)
    assert np.isclose(p_i, np.cos(eps / 2) ** 2, rtol=1e-5)
    assert p_x > 0
    assert np.isclose(p_x, np.sin(eps / 2) ** 2, rtol=1e-5)
    assert np.isclose(p_y, 0.0, atol=1e-12)
    assert np.isclose(p_z, 0.0, atol=1e-12)
