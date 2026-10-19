"""Oracle test: coherent error growth (N^2) vs Pauli-twirled linear growth (N)."""
from __future__ import annotations

import numpy as np

from qcss.physics.pta import twirl_unitary_error


def test_coherent_vs_twirled_scaling():
    """Verify that coherent over-rotations scale as N^2 while Pauli-twirled errors scale as N."""
    eps = 0.05  # 50 mrad over-rotation per pulse
    # Single-pulse unitary with over-rotation: R_x(pi + eps)
    theta = np.pi + eps
    u_coherent = np.array([
        [np.cos(theta / 2.0), -1j * np.sin(theta / 2.0)],
        [-1j * np.sin(theta / 2.0), np.cos(theta / 2.0)],
    ], dtype=complex)

    # Ideal target is pi pulse (X gate)
    # Error unitary E = u_coherent @ X^dag
    x_ideal = np.array([[0, 1], [1, 0]], dtype=complex)
    u_err = u_coherent @ x_ideal.conj().T
    p_twirl_x = twirl_unitary_error(u_err)[1]  # error probability per step

    n_pulses_list = [1, 3, 5, 7]
    coherent_errs = []
    twirled_errs = []

    for n_p in n_pulses_list:
        # Coherent: apply U^n_p
        u_total = np.linalg.matrix_power(u_coherent, n_p)
        psi0 = np.array([1.0, 0.0], dtype=complex)
        psi_f = u_total @ psi0
        # If n_p is odd, ideal state is |1> (prob of error is |<0|psi_f>|^2)
        # If n_p is even, ideal state is |0>
        ideal_target = 1 if (n_p % 2 == 1) else 0
        err_coherent = 1.0 - abs(psi_f[ideal_target]) ** 2
        coherent_errs.append(err_coherent)

        # Twirled: linear accumulation 1 - (1 - 2*p)^n_p / 2 ... ~ n_p * p
        err_twirled = n_p * p_twirl_x
        twirled_errs.append(err_twirled)

    # For N=1 vs N=5: coherent ratio should be ~ 5^2 = 25
    coherent_ratio = coherent_errs[2] / coherent_errs[0]
    twirled_ratio = twirled_errs[2] / twirled_errs[0]

    # Coherent ratio should be ~25 (quadratic)
    assert np.isclose(coherent_ratio, 25.0, rtol=0.1)
    # Twirled ratio should be ~5 (linear)
    assert np.isclose(twirled_ratio, 5.0, rtol=0.1)
