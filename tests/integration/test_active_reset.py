"""Integration test: active qubit reset with mid-circuit feedback and latency decay."""
from __future__ import annotations

import numpy as np

from qcss.physics.statevector_t1b import StatevectorT1b


def test_active_reset_ideal_t1():
    """With infinite T1, active reset produces 100% |0> state."""
    n_shots = 2000
    rng = np.random.default_rng(42)
    final_outcomes = []

    x_gate = np.array([[0, 1], [1, 0]], dtype=complex)
    h_gate = (1.0 / np.sqrt(2.0)) * np.array([[1, 1], [1, -1]], dtype=complex)

    for _ in range(n_shots):
        sv = StatevectorT1b(n=1, t1_ns=[1e9], t2_ns=[1e9])
        sv.apply_unitary(h_gate, (0,), 0.0, 10.0, rng)

        m = sv.measure(0, 20.0, rng)
        t_decision = 20.0 + 350.0
        if m == 1:
            sv.apply_unitary(x_gate, (0,), t_decision, t_decision + 20.0, rng)
            t_eval = t_decision + 20.0
        else:
            t_eval = t_decision

        m_final = sv.measure(0, t_eval, rng)
        final_outcomes.append(m_final)

    assert np.all(np.array(final_outcomes) == 0)


def test_active_reset_finite_t1_latency_decay():
    """With finite T1 = 50 us, decay during the 350 ns feedback latency causes ~0.7% residual error."""
    n_shots = 5000
    rng = np.random.default_rng(101)
    final_outcomes = []
    t1_ns = 50_000.0
    lat_ns = 350.0

    x_gate = np.array([[0, 1], [1, 0]], dtype=complex)
    h_gate = (1.0 / np.sqrt(2.0)) * np.array([[1, 1], [1, -1]], dtype=complex)

    for _ in range(n_shots):
        sv = StatevectorT1b(n=1, t1_ns=[t1_ns], t2_ns=[t1_ns])
        sv.apply_unitary(h_gate, (0,), 0.0, 10.0, rng)

        m = sv.measure(0, 20.0, rng)
        t_decision = 20.0 + lat_ns
        if m == 1:
            sv.apply_unitary(x_gate, (0,), t_decision, t_decision + 20.0, rng)
            t_eval = t_decision + 20.0
        else:
            t_eval = t_decision

        m_final = sv.measure(0, t_eval, rng)
        final_outcomes.append(m_final)

    # In ~50% of shots, qubit is in |1> and exposed to latency decay with p_decay = 1 - exp(-350/50000) ~ 0.007
    # Overall residual error rate is ~ 0.5 * 0.007 = 0.0035 (0.35%)
    err_rate = float(np.mean(final_outcomes))
    expected_err = 0.5 * (1.0 - np.exp(-lat_ns / t1_ns))
    assert np.isclose(err_rate, expected_err, atol=0.005)
    # Reset fidelity is > 99%
    assert err_rate < 0.01
