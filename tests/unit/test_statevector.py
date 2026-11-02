"""Unit tests for StatevectorT1b exact amplitude damping and lifter."""
from __future__ import annotations

import numpy as np
import pytest

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


def test_a_warm_qubit_relaxes_to_its_thermal_population():
    """Generalized amplitude damping: a long idle leaves P1 = nbar / (1 + 2 nbar), from either state."""
    from qcss.physics.statevector_t1b import StatevectorT1b
    nbar, t1 = 0.02, 50_000.0
    p_eq = nbar / (1 + 2 * nbar)
    rng = np.random.default_rng(1)
    ones = 0
    for k in range(4000):
        eng = StatevectorT1b(1, [t1], [40_000.0], nbar=[nbar], seed=k)
        if k % 2:
            eng.psi[:] = [0.0, 1.0]                        # start excited half of the time
        eng.advance_to(20 * t1, rng)
        ones += eng.measure(0, rng=rng)
    assert ones / 4000 == pytest.approx(p_eq, abs=0.008)


def test_a_long_idle_on_a_very_short_t1_costs_a_bounded_number_of_steps(monkeypatch):
    """A killed qubit (T1 ~ 1 ns) idling for a millisecond is simply thermalised: the work does not grow as
    dt / T1 (M7), and the qubit still lands on its thermal population."""
    from qcss.physics.statevector_t1b import StatevectorT1b
    nbar, t1 = 0.05, 1.0
    p_eq = nbar / (1 + 2 * nbar)
    calls = [0]
    real = StatevectorT1b._jump_down

    def counted(self, *args):
        calls[0] += 1
        return real(self, *args)

    monkeypatch.setattr(StatevectorT1b, "_jump_down", counted)
    rng = np.random.default_rng(3)
    ones = 0
    for k in range(2000):
        eng = StatevectorT1b(1, [t1], [1.0], nbar=[nbar], seed=k)
        eng.psi[:] = [0.0, 1.0]
        eng.advance_to(1e6, rng)                           # 10^6 T1 of idle
        ones += eng.measure(0, rng=rng)
    assert calls[0] / 2000 <= 300                          # was 10^7 steps per idle
    assert ones / 2000 == pytest.approx(p_eq, abs=0.015)


def test_a_warm_qubit_starts_thermally_excited():
    from qcss.physics.statevector_t1b import StatevectorT1b
    nbar = 0.05
    starts = [StatevectorT1b(1, [50_000.0], [40_000.0], nbar=[nbar], seed=k).level_probabilities(0)[1]
              for k in range(3000)]
    assert np.mean(starts) == pytest.approx(nbar / (1 + 2 * nbar), abs=0.012)


def test_the_measured_t1_is_unchanged_by_temperature():
    """T1 is what an experiment measures: the decay rate of P1 towards equilibrium is 1/T1 at any nbar."""
    from qcss.physics.statevector_t1b import StatevectorT1b
    nbar, t1 = 0.05, 50_000.0
    p_eq = nbar / (1 + 2 * nbar)
    rng = np.random.default_rng(2)
    ones = 0
    for k in range(4000):
        eng = StatevectorT1b(1, [t1], [40_000.0], nbar=[nbar], seed=k)
        eng.psi[:] = [0.0, 1.0]
        eng.advance_to(t1, rng)
        ones += eng.measure(0, rng=rng)
    assert ones / 4000 == pytest.approx(p_eq + (1 - p_eq) * np.exp(-1), abs=0.025)
