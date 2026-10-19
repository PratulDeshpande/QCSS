"""Unit tests for StatevectorT1b exact amplitude damping and lifter."""
from __future__ import annotations

import numpy as np

from qcss.physics.lifter import is_clifford_rz, lift_1q
from qcss.physics.statevector_t1b import StatevectorT1b


def test_statevector_t1b_unitary():
    sv = StatevectorT1b(n=2, t1_ns=[50_000.0, 50_000.0], t2_ns=[50_000.0, 50_000.0])
    rng = np.random.default_rng(42)

    # Apply Pauli X on qubit 0 (most significant axis)
    x = np.array([[0, 1], [1, 0]], dtype=complex)
    sv.apply_unitary(x, (0,), t_start=0.0, t_end=10.0, rng=rng)

    # State should now be |10> = index 2 (big-endian: 1*2 + 0 = 2)
    assert np.isclose(abs(sv.psi[2]) ** 2, 1.0, atol=1e-3)


def test_statevector_t1b_exact_amplitude_damping():
    """Start in |1>, idle for 2*T1: trajectory average P1 equals exp(-2) ~ 0.135."""
    t1_ns = 50_000.0
    n_shots = 3000
    rng = np.random.default_rng(999)

    outcomes = []
    x = np.array([[0, 1], [1, 0]], dtype=complex)

    for _ in range(n_shots):
        sv = StatevectorT1b(n=1, t1_ns=[t1_ns], t2_ns=[t1_ns])
        sv.apply_unitary(x, (0,), 0.0, 10.0, rng)  # prepare |1>
        # Idle for 2*T1 = 100 us
        sv.idle_until(10.0 + 100_000.0, rng)
        m = sv.measure(0, 10.0 + 100_000.0, rng)
        outcomes.append(m)

    mean_p1 = float(np.mean(outcomes))
    expected = np.exp(-2.0)  # ~0.1353
    # 5-sigma tolerance with 3000 shots is ~ 5 * sqrt(p(1-p)/N) ~ 5 * 0.0062 ~ 0.031
    assert np.isclose(mean_p1, expected, atol=0.035)


def test_statevector_t1b_zero_spectator_never_excited():
    """Qubit in |0> idling for 250 us must remain in |0> (amplitude damping does not excite)."""
    sv = StatevectorT1b(n=2, t1_ns=[50_000.0, 50_000.0], t2_ns=[50_000.0, 50_000.0])
    rng = np.random.default_rng(123)

    # Idle for 250 us
    sv.idle_until(250_000.0, rng)
    # Both qubits should still be in |0>
    m0 = sv.measure(0, 250_000.0, rng)
    m1 = sv.measure(1, 250_000.0, rng)
    assert m0 == 0
    assert m1 == 0
    assert np.isclose(abs(sv.psi[0]) ** 2, 1.0)


def test_lifter_1q_and_clifford():
    # 20 ns pi pulse at 25 MHz Rabi
    omega = np.full(20, 2 * np.pi * 0.025, dtype=complex)
    u2, leakage = lift_1q(omega, dt_ns=1.0, alpha_rad_ns=2 * np.pi * (-0.3))

    assert u2.shape == (2, 2)
    # Check that u2 is unitary within leakage
    prod = u2.conj().T @ u2
    assert np.allclose(prod, np.eye(2), atol=1e-2)
    assert leakage < 0.01

    # Clifford RZ checks
    assert is_clifford_rz(0.0)
    assert is_clifford_rz(np.pi / 2.0)
    assert is_clifford_rz(np.pi)
    assert is_clifford_rz(3.0 * np.pi / 2.0)
    assert not is_clifford_rz(0.123)
