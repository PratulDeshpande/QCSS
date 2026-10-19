"""Cross-tier test: Statevector T1b vs Lindblad T2 in the qubit limit."""
from __future__ import annotations

import numpy as np

from qcss.physics.lindblad_t2 import LindbladT2, QutritParams
from qcss.physics.statevector_t1b import StatevectorT1b


def test_t1b_vs_t2_qubit_limit_relaxation():
    """Verify that T1b trajectory average of sigma_z agrees with T2 Lindblad master equation."""
    t1_ns = 20_000.0
    t2_ns = 15_000.0
    t_idle = 10_000.0
    n_shots = 3000

    # 1. Statevector T1b with excited qubit |1> relaxing for t_idle
    rng = np.random.default_rng(42)
    p1_counts = 0
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    for _ in range(n_shots):
        sv = StatevectorT1b(1, [t1_ns], [t2_ns])
        sv.apply_unitary(X, (0,), 0.0, 0.0, rng)
        m = sv.measure(0, t_idle, rng)
        if m == 1:
            p1_counts += 1

    p1_t1b = p1_counts / n_shots

    # 2. Lindblad T2
    params = QutritParams(
        f01_ghz=[5.0],
        alpha_ghz=[-0.3],
        t1_ns=[t1_ns],
        t2_ns=[t2_ns],
        nbar=[0.0],
        frame_ghz=[5.0],
    )
    t2_sim = LindbladT2(params)
    # Set rho to |1><1|
    import qutip as qt
    t2_sim.rho = qt.basis(3, 1).proj()
    t2_sim.evolve_idle(0.0, t_idle)
    p1_t2 = float(t2_sim.level_probabilities(0)[1])

    # Expected analytical value: exp(-t / T1) = exp(-10000 / 20000) = exp(-0.5) ~ 0.6065
    p1_analytic = float(np.exp(-t_idle / t1_ns))
    sigma_stat = np.sqrt(p1_analytic * (1.0 - p1_analytic) / n_shots)

    # 5-sigma tolerance
    assert abs(p1_t1b - p1_t2) < 5 * sigma_stat, f"T1b {p1_t1b} and T2 {p1_t2} differ by > 5 sigma ({sigma_stat})"
