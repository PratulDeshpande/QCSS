"""Oracle tests for quantum error mitigation: Zero-Noise Extrapolation (ZNE) and PEC."""
from __future__ import annotations

import numpy as np

from qcss.physics.statevector_t1b import StatevectorT1b


def test_zero_noise_extrapolation_richardson():
    """Verify that Richardson ZNE reduces expectation value bias compared to unmitigated result."""
    t1_ns = 50_000.0
    t2_ns = 40_000.0
    gate_dur_ns = 20.0
    n_shots = 5000
    rng = np.random.default_rng(42)

    X = np.array([[0, 1], [1, 0]], dtype=complex)
    # Circuit: N pairs of X-X gates (identity logically, ideal <Z> = 1.0)
    n_pairs = 10

    def run_circuit_at_noise_scale(scale: float) -> float:
        # Scale noise by stretching gate duration or idle time
        scaled_gate_dur = gate_dur_ns * scale
        counts_0 = 0
        for _ in range(n_shots):
            sv = StatevectorT1b(1, [t1_ns], [t2_ns])
            t = 0.0
            for _ in range(n_pairs):
                sv.apply_unitary(X, (0,), t, t + scaled_gate_dur, rng)
                t += scaled_gate_dur
                sv.apply_unitary(X, (0,), t, t + scaled_gate_dur, rng)
                t += scaled_gate_dur
            m = sv.measure(0, t, rng)
            if m == 0:
                counts_0 += 1
        p0 = counts_0 / n_shots
        # <Z> = P(0) - P(1) = 2*P(0) - 1
        return 2.0 * p0 - 1.0

    # Scales: lambda = 1.0, lambda = 2.0
    z_1 = run_circuit_at_noise_scale(1.0)
    z_2 = run_circuit_at_noise_scale(2.0)

    # Ideal value is 1.0
    z_ideal = 1.0
    unmitigated_bias = abs(z_1 - z_ideal)

    # First-order Richardson extrapolation: Z_ext = 2*Z(1) - Z(2)
    z_zne = 2.0 * z_1 - z_2
    mitigated_bias = abs(z_zne - z_ideal)

    # Richardson extrapolation should reduce the bias compared to unmitigated
    assert mitigated_bias < unmitigated_bias, (
        f"ZNE failed to reduce bias: unmitigated={unmitigated_bias:.4f}, mitigated={mitigated_bias:.4f}"
    )


def test_probabilistic_error_cancellation_unbiased():
    """Verify that Probabilistic Error Cancellation (PEC) produces an unbiased expectation value."""
    # Under a known Pauli bit-flip channel with error probability p,
    # the inverted channel quasiprobability representation is:
    # E^{-1} = (1 - p)/(1 - 2p) * I - p/(1 - 2p) * X
    p = 0.04
    q_i = (1.0 - p) / (1.0 - 2.0 * p)
    q_x = -p / (1.0 - 2.0 * p)
    abs_sum = abs(q_i) + abs(q_x)
    gamma = abs_sum  # sum of absolute quasi-probabilities
    assert np.isclose(gamma, (1.0) / (1.0 - 2.0 * p))
    n_shots = 6000
    rng = np.random.default_rng(99)

    prob_i = abs(q_i) / abs_sum
    prob_x = abs(q_x) / abs_sum
    assert np.isclose(prob_i + prob_x, 1.0)

    X = np.array([[0, 1], [1, 0]], dtype=complex)
    pec_estimates = []
    for _ in range(n_shots):
        # Sample mitigation operator from quasi-probability distribution
        if rng.random() < prob_i:
            op_applied = "I"
            sign = np.sign(q_i)
        else:
            op_applied = "X"
            sign = np.sign(q_x)

        # Run the mitigation operation and the noisy gate on the T1b engine
        sv = StatevectorT1b(1, [1e12], [1e12])
        if op_applied == "X":
            sv.apply_unitary(X, (0,), 0.0, 0.0, rng)
        if rng.random() < p:                      # physical noise channel: bit flip with probability p
            sv.apply_unitary(X, (0,), 0.0, 0.0, rng)
        m_z = 1.0 if sv.measure(0, 0.0, rng) == 0 else -1.0
        estimator = abs_sum * sign * m_z
        pec_estimates.append(estimator)

    pec_mean = float(np.mean(pec_estimates))
    pec_sem = float(np.std(pec_estimates) / np.sqrt(n_shots))

    # Assert |<Z>_PEC - <Z>_ideal| <= 5 * sem
    assert abs(pec_mean - 1.0) <= 5.0 * pec_sem, (
        f"PEC estimator biased: mean={pec_mean:.4f}, sem={pec_sem:.4f}, bound={5*pec_sem:.4f}"
    )
